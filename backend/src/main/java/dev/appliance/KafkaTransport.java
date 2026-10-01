package dev.appliance;

import jakarta.annotation.PreDestroy;
import java.time.Duration;
import java.util.Properties;
import java.util.concurrent.TimeUnit;
import org.apache.kafka.clients.producer.*;
import org.apache.kafka.common.serialization.StringSerializer;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class KafkaTransport {
    private final boolean enabled;
    private final String topic;
    private final KafkaProducer<String,String> producer;
    public KafkaTransport(@Value("${app.kafka.enabled}") boolean enabled,
        @Value("${app.kafka.bootstrap-servers}") String bootstrap,@Value("${app.kafka.topic}") String topic) {
        this.enabled=enabled; this.topic=topic;
        if(!enabled) { producer=null; return; }
        Properties config=new Properties();
        config.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG,bootstrap);
        config.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG,StringSerializer.class.getName());
        config.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG,StringSerializer.class.getName());
        config.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG,"true");
        config.put(ProducerConfig.ACKS_CONFIG,"all");
        config.put(ProducerConfig.MAX_BLOCK_MS_CONFIG,"3000");
        config.put(ProducerConfig.REQUEST_TIMEOUT_MS_CONFIG,"3000");
        config.put(ProducerConfig.DELIVERY_TIMEOUT_MS_CONFIG,"5000");
        producer=new KafkaProducer<>(config);
    }
    public boolean enabled() { return enabled; }
    public void publish(String deviceId,String payload) throws Exception {
        if(producer==null) throw new IllegalStateException("Kafka disabled");
        producer.send(new ProducerRecord<>(topic,deviceId,payload)).get(6,TimeUnit.SECONDS);
    }
    @PreDestroy public void close() { if(producer!=null) producer.close(Duration.ofSeconds(2)); }
}
