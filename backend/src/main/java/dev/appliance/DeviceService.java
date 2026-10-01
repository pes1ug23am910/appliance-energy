package dev.appliance;

import static dev.appliance.Models.*;
import dev.appliance.CommandPolicy.StoredCommand;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.validation.Validator;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

@Service
public class DeviceService {
    private static final Instant EARLIEST_OBSERVATION=Instant.parse("1970-01-01T00:00:00Z");
    private final JdbcTemplate db;
    private final Json json;
    private final Validator validator;
    private final Clock clock;
    private final LiveSocket live;
    private final long staleSeconds;
    public DeviceService(JdbcTemplate db, Json json, Validator validator, Clock clock, LiveSocket live,
                         @Value("${app.device-stale-seconds}") long staleSeconds) {
        this.db=db; this.json=json; this.validator=validator; this.clock=clock; this.live=live; this.staleSeconds=staleSeconds;
    }
    static Timestamp ts(Instant instant) { return instant==null ? null : Timestamp.from(instant); }
    static Instant time(ResultSet rs,String name) throws SQLException {
        Timestamp value=rs.getTimestamp(name); return value==null ? null : value.toInstant();
    }
    public <T> void validate(T value) {
        var violations=validator.validate(value);
        if (!violations.isEmpty()) throw new ApiException(400,"Invalid message: "+violations.iterator().next().getPropertyPath());
    }
    public List<DeviceSnapshot> devices() {
        return db.query("SELECT * FROM devices ORDER BY device_id LIMIT 1000",this::snapshotRow);
    }
    public DeviceSnapshot device(String deviceId) {
        return db.query("SELECT * FROM devices WHERE device_id=?",this::snapshotRow,deviceId).stream()
            .findFirst().orElseThrow(()->new ApiException(404,"Device not found"));
    }
    private DeviceSnapshot snapshotRow(ResultSet rs,int row) throws SQLException {
        Instant seen=time(rs,"last_seen");
        Instant observed=time(rs,"reported_observed_at");
        String status=seen==null ? "never_seen" : seen.isBefore(clock.instant().minusSeconds(staleSeconds))
            || observed==null || observed.isBefore(clock.instant().minusSeconds(staleSeconds)) ? "stale" : "online";
        return new DeviceSnapshot(rs.getString("device_id"),rs.getString("name"),rs.getLong("desired_revision"),
            rs.getLong("reported_revision"),new Desired(rs.getBoolean("desired_power"),rs.getInt("desired_speed")),
            new Desired(rs.getBoolean("reported_power"),rs.getInt("reported_speed")),seen,status);
    }
    @Transactional
    public DeviceSnapshot register(DeviceRequest request) {
        validate(request);
        int inserted=db.update("INSERT INTO devices(device_id,name) VALUES (?,?) ON CONFLICT DO NOTHING",request.deviceId(),request.name());
        if (inserted==0 && !device(request.deviceId()).name().equals(request.name())) throw new ApiException(409,"Device already registered with another name");
        changed(request.deviceId(),null);
        return device(request.deviceId());
    }
    private void lockDevice(String deviceId) {
        if(db.queryForList("SELECT device_id FROM devices WHERE device_id=? FOR UPDATE",deviceId).isEmpty())
            throw new ApiException(404,"Device not found");
    }
    private StoredCommand commandRow(ResultSet rs,int row) throws SQLException {
        return new StoredCommand(rs.getObject("command_id",UUID.class),rs.getString("device_id"),rs.getLong("expected_revision"),
            rs.getLong("revision"),rs.getBoolean("power"),rs.getInt("speed_percent"),time(rs,"expires_at"),
            time(rs,"created_at"),time(rs,"attempted_at"),rs.getString("status"));
    }
    Optional<StoredCommand> stored(UUID id) {
        return db.query("SELECT * FROM commands WHERE command_id=?",this::commandRow,id).stream().findFirst();
    }
    public CommandReceipt command(UUID id) {
        return stored(id).orElseThrow(()->new ApiException(404,"Command not found")).receipt();
    }
    @Transactional
    public CommandReceipt submit(String deviceId,CommandRequest request) {
        validate(request);
        db.queryForList("SELECT pg_advisory_xact_lock(hashtextextended(?,0))",request.commandId().toString());
        var previous=stored(request.commandId());
        if(previous.isPresent()) {
            if(!CommandPolicy.equivalent(deviceId,request,previous.get())) throw new ApiException(409,"Command ID payload conflict");
            return previous.get().receipt();
        }
        Instant expiry=CommandPolicy.precision(request.expiresAt());
        if(!expiry.isAfter(clock.instant())) throw new ApiException(400,"Command already expired");
        if(expiry.isAfter(clock.instant().plusSeconds(86400))) throw new ApiException(400,"Command expiry exceeds 24 hours");
        lockDevice(deviceId);
        DeviceSnapshot snapshot=device(deviceId);
        if(snapshot.desiredRevision()!=request.expectedRevision()) throw new ApiException(409,"Desired revision conflict");
        if(snapshot.desiredRevision()==Long.MAX_VALUE) throw new ApiException(409,"Revision exhausted");
        long revision=snapshot.desiredRevision()+1;
        var superseded=db.queryForList("UPDATE commands SET status='superseded' WHERE device_id=? AND status IN ('accepted','awaiting_device') RETURNING command_id",UUID.class,deviceId);
        db.update("INSERT INTO commands(command_id,device_id,expected_revision,revision,power,speed_percent,expires_at,status) VALUES (?,?,?,?,?,?,?,'accepted')",
            request.commandId(),deviceId,request.expectedRevision(),revision,request.desired().power(),request.desired().speedPercent(),ts(expiry));
        db.update("UPDATE devices SET desired_revision=?,desired_power=?,desired_speed=? WHERE device_id=?",
            revision,request.desired().power(),request.desired().speedPercent(),deviceId);
        CommandReceipt receipt=command(request.commandId());
        queueDesired(receipt);
        superseded.forEach(id->changed(null,id));
        changed(deviceId,request.commandId());
        return receipt;
    }
    void queue(String kind,String key,String deviceId,Object payload,boolean retry) {
        String conflict=retry ? "DO UPDATE SET published_at=NULL,available_at=now(),payload=EXCLUDED.payload,last_error=NULL" : "DO NOTHING";
        db.update("INSERT INTO outbox(kind,dedup_key,device_id,payload) VALUES (?,?,?,?::jsonb) ON CONFLICT(kind,dedup_key) "+conflict,
            kind,key,deviceId,json.write(payload));
    }
    void queueDesired(CommandReceipt command) {
        queue("desired",command.commandId().toString(),command.deviceId(),Map.of(
            "command_id",command.commandId(),"device_id",command.deviceId(),"revision",command.revision(),
            "desired",command.desired(),"expires_at",command.expiresAt()),true);
    }
    @Transactional
    public void sync(String topicDevice,Sync sync) {
        validate(sync); matchDevice(topicDevice,sync.deviceId()); lockDevice(topicDevice);
        db.query("SELECT c.* FROM commands c JOIN devices d ON d.device_id=c.device_id AND d.desired_revision=c.revision WHERE c.device_id=? AND c.expires_at>? AND c.status NOT IN ('expired','superseded','rejected')",
            this::commandRow,topicDevice,ts(clock.instant())).forEach(c->queueDesired(c.receipt()));
    }
    @Transactional
    public void report(String topicDevice,Report report) {
        validate(report); matchDevice(topicDevice,report.deviceId()); lockDevice(topicDevice);
        DeviceSnapshot current=device(topicDevice);
        if(report.revision()>current.desiredRevision()) throw new ApiException(409,"Reported revision exceeds desired revision");
        validateObservationTime(report.observedAt());
        if(report.commandId()!=null) {
            StoredCommand cmd=stored(report.commandId()).orElseThrow(()->new ApiException(409,"Unknown report command"));
            if(!cmd.deviceId().equals(topicDevice) || cmd.revision()!=report.revision()) throw new ApiException(409,"Report command mismatch");
        }
        Map<String,Object> state=db.queryForMap("SELECT reported_boot,reported_sequence,reported_observed_at FROM devices WHERE device_id=?",topicDevice);
        Long lastSeq=(Long)state.get("reported_sequence");
        UUID lastBoot=(UUID)state.get("reported_boot");
        Timestamp lastObserved=(Timestamp)state.get("reported_observed_at");
        if(report.revision()<current.reportedRevision()) return;
        boolean sameBoot=report.bootId().equals(lastBoot);
        if(sameBoot && lastSeq!=null && report.sequence()<=lastSeq) {
            if(report.sequence().equals(lastSeq) && (report.revision()!=current.reportedRevision()
                || !report.power().equals(current.reported().power()) || !report.speedPercent().equals(current.reported().speedPercent())))
                throw new ApiException(409,"Conflicting report sequence");
            return;
        }
        if(!sameBoot && lastObserved!=null && report.observedAt().isBefore(lastObserved.toInstant())) return;
        db.update("UPDATE devices SET reported_revision=?,reported_power=?,reported_speed=?,reported_boot=?,reported_sequence=?,reported_observed_at=?,last_seen=? WHERE device_id=?",
            report.revision(),report.power(),report.speedPercent(),report.bootId(),report.sequence(),ts(report.observedAt()),ts(clock.instant()),topicDevice);
        if(report.commandId()!=null) {
            StoredCommand cmd=stored(report.commandId()).orElseThrow();
            // Confirmation proves observed convergence, not execution before the dispatch deadline.
            if(cmd.revision()==current.desiredRevision() && cmd.power()==report.power() && cmd.speedPercent()==report.speedPercent()) {
                db.update("UPDATE commands SET status='confirmed' WHERE command_id=? AND status IN ('accepted','awaiting_device','outcome_unknown')",cmd.commandId());
                changed(null,cmd.commandId());
            }
        }
        changed(topicDevice,null);
    }
    @Transactional
    public void telemetry(String topicDevice,TelemetryEvent event) {
        validate(event); matchDevice(topicDevice,event.deviceId());
        if(!Double.isFinite(event.powerW()) || !Double.isFinite(event.energyWhTotal())) throw new ApiException(400,"Nonfinite measurement");
        validateObservationTime(event.eventTime());
        if(!db.queryForObject("SELECT EXISTS(SELECT 1 FROM devices WHERE device_id=?)",Boolean.class,topicDevice)) throw new ApiException(404,"Device not found");
        String hash=json.hash(event);
        Instant received=clock.instant();
        ObjectNode normalized=(ObjectNode)json.tree(json.write(event));
        normalized.put("received_at",received.toString());
        int inserted=db.update("INSERT INTO telemetry(event_id,device_id,boot_id,sequence,event_time,received_at,payload,payload_hash) VALUES (?,?,?,?,?,?,?::jsonb,?) ON CONFLICT DO NOTHING",
            event.eventId(),topicDevice,event.bootId(),event.sequence(),ts(event.eventTime()),ts(received),json.write(normalized),hash);
        if(inserted==0) {
            var rows=db.queryForList("SELECT event_id,payload_hash FROM telemetry WHERE event_id=? OR (device_id=? AND boot_id=? AND sequence=?)",
                event.eventId(),topicDevice,event.bootId(),event.sequence());
            if(rows.size()!=1 || !event.eventId().equals(rows.getFirst().get("event_id")) || !hash.equals(rows.getFirst().get("payload_hash")))
                throw new ApiException(409,"Conflicting immutable telemetry identity");
        } else {
            queue("telemetry",event.eventId().toString(),topicDevice,normalized,false);
        }
        queue("receipt",event.eventId().toString(),topicDevice,Map.of("event_id",event.eventId(),"status","accepted"),true);
    }
    public List<JsonNode> telemetry(String deviceId,int limit) {
        device(deviceId);
        if(limit<1 || limit>1000) throw new ApiException(400,"Telemetry limit must be between 1 and 1000");
        return db.query("SELECT payload::text FROM telemetry WHERE device_id=? ORDER BY received_at DESC,event_id LIMIT ?",
            (rs,row)->json.tree(rs.getString(1)),deviceId,limit);
    }
    public void quarantine(String topic,String payload,String reason) {
        db.update("INSERT INTO quarantine(topic,payload,reason) VALUES (?,?,?)",
            clip(topic,256),clip(payload,65536),clip(reason==null?"Invalid message":reason,1000));
    }
    private static String clip(String value,int max) { return value.length()>max ? value.substring(0,max) : value; }
    private static void matchDevice(String topic,String payload) {
        if(!topic.equals(payload)) throw new ApiException(403,"Topic and payload device mismatch");
    }
    private void validateObservationTime(Instant observation) {
        if(observation.isBefore(EARLIEST_OBSERVATION) || observation.isAfter(clock.instant().plusSeconds(300)))
            throw new ApiException(400,"Observation timestamp must be between 1970-01-01 UTC and server time plus 300 seconds");
    }
    void changed(String deviceId,UUID commandId) {
        Runnable notification=()-> {
            if(deviceId!=null) live.broadcast(Map.of("type","device_updated","device",device(deviceId)));
            if(commandId!=null) live.broadcast(Map.of("type","command_updated","command",command(commandId)));
        };
        if(TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override public void afterCommit() { notification.run(); }
            });
        } else notification.run();
    }
}
