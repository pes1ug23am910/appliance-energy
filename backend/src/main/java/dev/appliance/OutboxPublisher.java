package dev.appliance;

import jakarta.annotation.PreDestroy;
import java.util.concurrent.*;
import java.util.stream.IntStream;
import org.slf4j.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class OutboxPublisher {
    private static final Logger log=LoggerFactory.getLogger(OutboxPublisher.class);
    private final OutboxStore store;
    private final MqttTransport mqtt;
    private final KafkaTransport kafka;
    private final DeviceService service;
    private final int concurrency;
    private final ExecutorService workers;
    public OutboxPublisher(OutboxStore store,MqttTransport mqtt,KafkaTransport kafka,DeviceService service,
        @Value("${OUTBOX_CONCURRENCY:8}") int concurrency) {
        this.store=store; this.mqtt=mqtt; this.kafka=kafka; this.service=service;
        if(concurrency<1 || concurrency>8) throw new IllegalArgumentException("OUTBOX_CONCURRENCY must be 1..8");
        this.concurrency=concurrency;
        this.workers=Executors.newFixedThreadPool(concurrency);
    }
    @Scheduled(fixedDelayString="${OUTBOX_POLL_MS:100}",initialDelayString="${OUTBOX_INITIAL_DELAY_MS:1000}")
    public void publishBatch() {
        store.expireCommands();
        CompletableFuture.allOf(IntStream.range(0,concurrency)
            .mapToObj(i->CompletableFuture.runAsync(this::drain,workers))
            .toArray(CompletableFuture[]::new)).join();
    }
    private void drain() {
        // Claim just before delivery: queued futures must not consume the lease.
        for(int i=0;i<32;i++) {
            var claim=store.claim(mqtt.connected(),kafka.enabled());
            if(claim==null) return;
            try {
                if("telemetry".equals(claim.kind())) kafka.publish(claim.deviceId(),claim.payload());
                else {
                    if("desired".equals(claim.kind())) {
                        var command=service.command(java.util.UUID.fromString(claim.key()));
                        if(!command.expiresAt().isAfter(java.time.Instant.now())
                            || command.revision()!=service.device(claim.deviceId()).desiredRevision()) { store.delivered(claim); continue; }
                    }
                    mqtt.publish("devices/"+claim.deviceId()+"/"+claim.kind(),claim.payload());
                }
                store.delivered(claim);
            } catch(Exception failure) {
                store.failed(claim,failure);
                log.warn("Outbox delivery pending for kind {}: {}",claim.kind(),failure.getClass().getSimpleName());
            }
        }
    }
    @PreDestroy public void close() {
        workers.shutdown();
        try { if(!workers.awaitTermination(10,TimeUnit.SECONDS)) workers.shutdownNow(); }
        catch(InterruptedException interrupted) { workers.shutdownNow(); Thread.currentThread().interrupt(); }
    }
}
