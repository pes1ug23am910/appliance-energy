package dev.appliance;

import static org.junit.jupiter.api.Assertions.*;
import static dev.appliance.Models.*;
import com.fasterxml.jackson.databind.JsonNode;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.dao.DataAccessException;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={
    "app.api-token=integration-test-token-0123456789","app.mqtt.enabled=false","app.kafka.enabled=false",
    "app.ws-auth-timeout-seconds=1","OUTBOX_INITIAL_DELAY_MS=3600000"})
@EnabledIfEnvironmentVariable(named="TEST_DATABASE_URL",matches=".+")
class PostgresIntegrationTest {
    @DynamicPropertySource static void database(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url",()->System.getenv("TEST_DATABASE_URL"));
        registry.add("spring.datasource.username",()->System.getenv().getOrDefault("TEST_DATABASE_USERNAME","appliance"));
        registry.add("spring.datasource.password",()->System.getenv().getOrDefault("TEST_DATABASE_PASSWORD","appliance-test"));
    }
    @Autowired DeviceService service;
    @Autowired JdbcTemplate db;
    @Autowired Json json;
    @Autowired MqttIngress ingress;
    @Autowired OutboxStore outbox;
    @Autowired TestRestTemplate http;
    @Autowired LiveSocket live;
    @Autowired PlatformTransactionManager transactions;
    @LocalServerPort int port;
    @BeforeEach void reset() {
        db.execute("TRUNCATE outbox,telemetry,quarantine,commands,devices RESTART IDENTITY CASCADE");
        service.register(new DeviceRequest("device-001","Test device"));
    }
    CommandRequest request(long revision) {
        return new CommandRequest(UUID.randomUUID(),revision,new Desired(true,40),CommandPolicy.precision(Instant.now().plusSeconds(120)));
    }
    @Test void duplicateRequestsReturnOneCommandAndConflictOnMutation() {
        var request=request(0);
        var accepted=service.submit("device-001",request);
        for(int i=0;i<10;i++) assertEquals(accepted,service.submit("device-001",request));
        assertEquals(1,db.queryForObject("SELECT count(*) FROM commands",Integer.class));
        assertEquals(1,db.queryForObject("SELECT count(*) FROM outbox WHERE kind='desired'",Integer.class));
        var changed=new CommandRequest(request.commandId(),0L,new Desired(false,40),request.expiresAt());
        assertEquals(409,assertThrows(ApiException.class,()->service.submit("device-001",changed)).status());
    }
    @Test void concurrentRevisionEditsAcceptExactlyOneAndConcurrentIdRetriesConverge() throws Exception {
        var requests=List.of(request(0),request(0));
        try(var pool=Executors.newFixedThreadPool(2)) {
            var gate=new CountDownLatch(1);
            var tasks=requests.stream().map(r->pool.submit(()-> {
                gate.await(); try { service.submit("device-001",r); return 200; } catch(ApiException e) { return e.status(); }
            })).toList();
            gate.countDown();
            var statuses=new ArrayList<Integer>(); for(var result:tasks) statuses.add(result.get(5,TimeUnit.SECONDS));
            Collections.sort(statuses); assertEquals(List.of(200,409),statuses);
            var repeated=request(1);
            var a=pool.submit(()->service.submit("device-001",repeated));
            var b=pool.submit(()->service.submit("device-001",repeated));
            assertEquals(a.get(5,TimeUnit.SECONDS),b.get(5,TimeUnit.SECONDS));
        }
        assertEquals(2,service.device("device-001").desiredRevision());
    }
    @Test void expiryDistinguishesNeverDispatchedFromUncertainAndSupersedesPending() {
        var first=service.submit("device-001",request(0));
        var second=service.submit("device-001",request(1));
        assertEquals("superseded",service.command(first.commandId()).status());
        db.update("UPDATE commands SET expires_at=now()-interval '1 second' WHERE command_id=?",second.commandId());
        outbox.expireCommands(); assertEquals("expired",service.command(second.commandId()).status());
        var third=service.submit("device-001",request(2));
        while(outbox.claim(true,false)==null) {
            if(db.queryForObject("SELECT count(*) FROM outbox WHERE published_at IS NULL",Integer.class)==0) fail("No claim");
        }
        db.update("UPDATE commands SET expires_at=now()-interval '1 second' WHERE command_id=?",third.commandId());
        outbox.expireCommands(); assertEquals("outcome_unknown",service.command(third.commandId()).status());
    }
    TelemetryEvent event(UUID eventId,UUID boot,long sequence,double power) {
        return new TelemetryEvent(1,eventId,"device-001",boot,sequence,Instant.parse("2026-01-01T00:00:00Z"),
            "simulated",power,20.0,"sim-1",List.of());
    }
    @Test void immutableTelemetryDeduplicatesConflictsQuarantineAndLostReceiptsRetry() {
        UUID id=UUID.randomUUID(),boot=UUID.randomUUID(); var event=event(id,boot,1,10);
        ingress.accept("devices/device-001/telemetry",json.write(event));
        db.update("UPDATE outbox SET published_at=now() WHERE kind='receipt'");
        ingress.accept("devices/device-001/telemetry",json.write(event));
        assertEquals(1,db.queryForObject("SELECT count(*) FROM telemetry",Integer.class));
        assertEquals(1,db.queryForObject("SELECT count(*) FROM outbox WHERE kind='telemetry'",Integer.class));
        assertEquals(1,db.queryForObject("SELECT count(*) FROM outbox WHERE kind='receipt' AND published_at IS NULL",Integer.class));
        ingress.accept("devices/device-001/telemetry",json.write(event(id,boot,1,11)));
        ingress.accept("devices/device-001/telemetry",json.write(event(UUID.randomUUID(),boot,1,10)));
        ingress.accept("devices/another/telemetry",json.write(event));
        assertEquals(3,db.queryForObject("SELECT count(*) FROM quarantine",Integer.class));
        assertEquals(1,service.telemetry("device-001",100).size());
        assertEquals("simulated",service.telemetry("device-001",1).getFirst().path("source_kind").asText());
        assertTrue(service.telemetry("device-001",1).getFirst().has("received_at"));
    }
    @Test void reportsCannotRegressRevisionOrFalselyConfirmAndSyncRequeuesLatest() {
        var command=service.submit("device-001",request(0)); UUID boot=UUID.randomUUID();
        Instant now=Instant.now();
        service.report("device-001",new Report("device-001",boot,1L,1L,false,0,now,"sim-1",command.commandId()));
        assertEquals("accepted",service.command(command.commandId()).status());
        service.report("device-001",new Report("device-001",boot,2L,1L,true,40,now.plusMillis(1),"sim-1",command.commandId()));
        assertEquals("confirmed",service.command(command.commandId()).status());
        service.report("device-001",new Report("device-001",boot,3L,0L,false,0,now.plusMillis(2),"sim-1",null));
        assertEquals(1,service.device("device-001").reportedRevision());
        assertEquals(409,assertThrows(ApiException.class,()->service.report("device-001",new Report("device-001",boot,4L,2L,true,40,now,"sim-1",null))).status());
        db.update("UPDATE outbox SET published_at=now()");
        service.sync("device-001",new Sync("device-001",boot));
        assertEquals(1,db.queryForObject("SELECT count(*) FROM outbox WHERE kind='desired' AND published_at IS NULL",Integer.class));
    }
    @Test void outboxAttemptSurvivesFailureAndReplaysWithoutAddingLogicalEvents() {
        var command=service.submit("device-001",request(0));
        var claim=outbox.claim(true,false); assertNotNull(claim);
        assertNotNull(db.queryForObject("SELECT attempted_at FROM commands WHERE command_id=?",java.sql.Timestamp.class,command.commandId()));
        outbox.failed(claim,new IllegalStateException("network down"));
        assertEquals(0,db.queryForObject("SELECT count(*) FROM outbox WHERE published_at IS NOT NULL",Integer.class));
        db.update("UPDATE outbox SET available_at=now()");
        var retry=outbox.claim(true,false); assertEquals(claim.id(),retry.id()); assertEquals(2,retry.attempt());
        outbox.delivered(retry); assertEquals("awaiting_device",service.command(command.commandId()).status());
    }
    @Test void lateMatchingReportResolvesUncertaintyButCannotConfirmAnOlderIntent() {
        var first=service.submit("device-001",request(0));
        assertNotNull(outbox.claim(true,false));
        db.update("UPDATE commands SET expires_at=now()-interval '1 second' WHERE command_id=?",first.commandId());
        outbox.expireCommands();
        assertEquals("outcome_unknown",service.command(first.commandId()).status());
        UUID boot=UUID.randomUUID();
        service.report("device-001",new Report("device-001",boot,1L,1L,true,40,Instant.now(),"sim-1",first.commandId()));
        assertEquals("confirmed",service.command(first.commandId()).status());
        var second=service.submit("device-001",request(1));
        db.update("UPDATE commands SET status='outcome_unknown',expires_at=now()-interval '1 second' WHERE command_id=?",second.commandId());
        service.submit("device-001",request(2));
        service.report("device-001",new Report("device-001",boot,2L,2L,true,40,Instant.now(),"sim-1",second.commandId()));
        assertEquals("outcome_unknown",service.command(second.commandId()).status());
    }
    @Test void reportSequenceWinsWithinBootAndConflictsBeyondBoxedIntegerCacheAreRejected() {
        var command=service.submit("device-001",request(0));
        UUID boot=UUID.randomUUID(); Instant now=Instant.now();
        service.report("device-001",new Report("device-001",boot,1000L,1L,false,0,now,"sim-1",command.commandId()));
        assertEquals(409,assertThrows(ApiException.class,()->service.report("device-001",
            new Report("device-001",boot,1000L,1L,true,40,now,"sim-1",command.commandId()))).status());
        service.report("device-001",new Report("device-001",boot,1001L,1L,true,40,now.minusSeconds(10),"sim-1",command.commandId()));
        assertTrue(service.device("device-001").reported().power());
        assertEquals("confirmed",service.command(command.commandId()).status());
        service.report("device-001",new Report("device-001",UUID.randomUUID(),1L,1L,false,0,
            now.minusSeconds(20),"sim-1",command.commandId()));
        assertTrue(service.device("device-001").reported().power());
        assertEquals(1001L,db.queryForObject("SELECT reported_sequence FROM devices WHERE device_id='device-001'",Long.class));
    }
    @Test void impossibleObservationTimesAreQuarantinedBeforeDatabaseConversion() {
        var times=List.of(Instant.parse("1969-12-31T23:59:59Z"),Instant.now().plusSeconds(600),
            Instant.parse("+500000-01-01T00:00:00Z"),Instant.MAX);
        for(Instant time:times) {
            var invalid=new TelemetryEvent(1,UUID.randomUUID(),"device-001",UUID.randomUUID(),1L,time,
                "simulated",10.0,20.0,"sim-1",List.of());
            ingress.accept("devices/device-001/telemetry",json.write(invalid));
            ingress.accept("devices/device-001/reported",json.write(new Report("device-001",UUID.randomUUID(),
                1L,0L,false,0,time,"sim-1",null)));
        }
        assertEquals(8,db.queryForObject("SELECT count(*) FROM quarantine",Integer.class));
        assertEquals(0,db.queryForObject("SELECT count(*) FROM telemetry",Integer.class));
        assertEquals(0,db.queryForObject("SELECT count(*) FROM outbox",Integer.class));
        assertEquals("never_seen",service.device("device-001").status());
    }
    @Test void concurrentOutboxClaimsSkipLockedRowsAndHoldDistinctLeases() throws Exception {
        for(int i=0;i<5;i++) service.telemetry("device-001",event(UUID.randomUUID(),UUID.randomUUID(),1,10));
        var ids=ConcurrentHashMap.<Long>newKeySet();
        try(var pool=Executors.newFixedThreadPool(8)) {
            new TransactionTemplate(transactions).executeWithoutResult(status->{
                long locked=db.queryForObject("SELECT id FROM outbox ORDER BY id LIMIT 1 FOR UPDATE",Long.class);
                try {
                    var other=pool.submit(()->outbox.claim(true,true)).get(5,TimeUnit.SECONDS);
                    assertNotNull(other); assertNotEquals(locked,other.id()); assertTrue(ids.add(other.id()));
                } catch(Exception error) { throw new AssertionError(error); }
            });
            var start=new CountDownLatch(1);
            var tasks=new ArrayList<Future<?>>();
            for(int i=0;i<8;i++) tasks.add(pool.submit(()->{
                start.await();
                OutboxStore.Claim claim;
                while((claim=outbox.claim(true,true))!=null) assertTrue(ids.add(claim.id()),"Claimed active lease twice");
                return null;
            }));
            start.countDown();
            for(var task:tasks) task.get(10,TimeUnit.SECONDS);
        }
        assertEquals(10,ids.size());
        assertNull(outbox.claim(true,true));
        assertEquals(10,db.queryForObject("SELECT count(*) FROM outbox WHERE attempts=1 AND available_at>now()",Integer.class));
    }
    @Test void databaseFailureCannotCommitCommandOrTelemetryWithoutItsOutbox() {
        db.execute("CREATE FUNCTION fail_test_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected outbox failure'; END $$");
        db.execute("CREATE TRIGGER fail_test_outbox BEFORE INSERT ON outbox FOR EACH ROW EXECUTE FUNCTION fail_test_outbox()");
        try {
            assertThrows(DataAccessException.class,()->service.submit("device-001",request(0)));
            assertEquals(0,db.queryForObject("SELECT count(*) FROM commands",Integer.class));
            assertEquals(0,service.device("device-001").desiredRevision());
            assertThrows(DataAccessException.class,()->ingress.accept("devices/device-001/telemetry",
                json.write(event(UUID.randomUUID(),UUID.randomUUID(),1,10))));
            assertEquals(0,db.queryForObject("SELECT count(*) FROM telemetry",Integer.class));
            assertEquals(0,db.queryForObject("SELECT count(*) FROM outbox",Integer.class));
        } finally {
            db.execute("DROP TRIGGER fail_test_outbox ON outbox");
            db.execute("DROP FUNCTION fail_test_outbox()");
        }
    }
    @Test void oldObservationDoesNotMasqueradeAsLiveEvenWhenJustReceived() {
        service.report("device-001",new Report("device-001",UUID.randomUUID(),1L,0L,false,0,
            Instant.now().minusSeconds(3600),"sim-1",null));
        assertEquals("stale",service.device("device-001").status());
    }
    @Test void httpRequiresTokenValidatesBoundsAndSupportsApprovedCors() {
        assertEquals(401,http.getForEntity("/api/devices",String.class).getStatusCode().value());
        assertEquals(401,http.getForEntity("/api;parameter/devices",String.class).getStatusCode().value());
        HttpHeaders headers=new HttpHeaders(); headers.setBearerAuth("integration-test-token-0123456789");
        assertEquals(200,http.exchange("/api/devices",HttpMethod.GET,new HttpEntity<>(headers),String.class).getStatusCode().value());
        assertEquals(400,http.exchange("/api/devices/device-001/telemetry?limit=1001",HttpMethod.GET,new HttpEntity<>(headers),String.class).getStatusCode().value());
        headers=new HttpHeaders(); headers.setOrigin("http://localhost:8090");
        headers.setAccessControlRequestMethod(HttpMethod.POST); headers.setAccessControlRequestHeaders(List.of("Authorization","Content-Type"));
        var response=http.exchange("/api/devices",HttpMethod.OPTIONS,new HttpEntity<>(headers),String.class);
        assertEquals(200,response.getStatusCode().value()); assertEquals("http://localhost:8090",response.getHeaders().getAccessControlAllowOrigin());
    }
    @Test void websocketSendsNothingBeforeAuthAndClosesIdleUnauthenticated() throws Exception {
        var frames=new LinkedBlockingQueue<String>(); var closed=new CompletableFuture<Integer>();
        WebSocket.Listener listener=new WebSocket.Listener() {
            @Override public void onOpen(WebSocket ws) { ws.request(1); }
            @Override public CompletionStage<?> onText(WebSocket ws,CharSequence data,boolean last) { frames.add(data.toString()); ws.request(1); return null; }
            @Override public CompletionStage<?> onClose(WebSocket ws,int code,String reason) { closed.complete(code); return null; }
        };
        var client=HttpClient.newHttpClient();
        var ws=client.newWebSocketBuilder().buildAsync(URI.create("ws://localhost:"+port+"/ws"),listener).get(5,TimeUnit.SECONDS);
        live.broadcast(Map.of("type","secret")); assertNull(frames.poll(100,TimeUnit.MILLISECONDS));
        ws.sendText("{\"type\":\"authenticate\",\"token\":\"integration-test-token-0123456789\"}",true).get();
        assertTrue(frames.poll(2,TimeUnit.SECONDS).contains("authenticated"));
        live.broadcast(Map.of("type","device_updated")); assertTrue(frames.poll(2,TimeUnit.SECONDS).contains("device_updated"));
        ws.sendClose(1000,"done").get();
        var idleClosed=new CompletableFuture<Integer>();
        client.newWebSocketBuilder().buildAsync(URI.create("ws://localhost:"+port+"/ws"),new WebSocket.Listener() {
            @Override public CompletionStage<?> onClose(WebSocket socket,int code,String reason) { idleClosed.complete(code); return null; }
        }).get(5,TimeUnit.SECONDS);
        assertEquals(1008,idleClosed.get(4,TimeUnit.SECONDS));
    }
}
