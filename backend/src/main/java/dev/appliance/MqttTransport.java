package dev.appliance;

import jakarta.annotation.PreDestroy;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.*;
import org.eclipse.paho.client.mqttv3.*;
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence;
import org.slf4j.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class MqttTransport {
    private static final Logger log=LoggerFactory.getLogger(MqttTransport.class);
    private final boolean enabled;
    private final MqttIngress ingress;
    private final String uri,username,password,caCert,clientId;
    private volatile MqttClient client;
    private final AtomicBoolean connecting=new AtomicBoolean();
    public MqttTransport(MqttIngress ingress,@Value("${app.mqtt.enabled}") boolean enabled,
        @Value("${app.mqtt.uri}") String uri,@Value("${app.mqtt.username}") String username,
        @Value("${app.mqtt.password}") String password,@Value("${app.mqtt.ca-cert}") String caCert,
        @Value("${app.mqtt.client-id}") String clientId) {
        if(enabled && !uri.startsWith("ssl://")) throw new IllegalStateException("MQTT_URI must use ssl://");
        this.ingress=ingress; this.enabled=enabled; this.uri=uri; this.username=username; this.password=password; this.caCert=caCert; this.clientId=clientId;
    }
    public boolean enabled() { return enabled; }
    public boolean connected() { return client!=null && client.isConnected(); }
    @Scheduled(fixedDelay=3000,initialDelay=1000)
    public void connect() {
        if(!enabled || connected() || !connecting.compareAndSet(false,true)) return;
        try {
            if(client==null) {
                client=new MqttClient(uri,clientId,new MemoryPersistence()); client.setManualAcks(true); client.setTimeToWait(5000);
                client.setCallback(new MqttCallback() {
                    @Override public void connectionLost(Throwable cause) { log.warn("MQTT disconnected"); }
                    @Override public void deliveryComplete(IMqttDeliveryToken token) {}
                    @Override public void messageArrived(String topic,MqttMessage message) throws Exception {
                        if(message.isRetained()) {
                            ingress.rejectRetained(topic,new String(message.getPayload(),StandardCharsets.UTF_8));
                            client.messageArrivedComplete(message.getId(),message.getQos()); return;
                        }
                        ingress.accept(topic,new String(message.getPayload(),StandardCharsets.UTF_8));
                        client.messageArrivedComplete(message.getId(),message.getQos());
                    }
                });
            }
            MqttConnectOptions options=new MqttConnectOptions();
            options.setCleanSession(false); options.setAutomaticReconnect(false); options.setConnectionTimeout(3);
            options.setKeepAliveInterval(20); options.setUserName(username); options.setPassword(password.toCharArray());
            options.setHttpsHostnameVerificationEnabled(true);
            options.setSocketFactory(sslContext().getSocketFactory());
            client.connect(options);
            client.subscribe(new String[]{"devices/+/telemetry","devices/+/reported","devices/+/sync"},new int[]{1,1,1});
            log.info("MQTT connected with TLS and manual acknowledgements");
        } catch(Exception failure) {
            log.warn("MQTT connection unavailable: {}",failure.getClass().getSimpleName());
            try { if(client!=null && client.isConnected()) client.disconnectForcibly(0,1000); } catch(MqttException ignored) {}
        }
        finally { connecting.set(false); }
    }
    private SSLContext sslContext() throws Exception {
        TrustManagerFactory factory=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        if(caCert==null || caCert.isBlank()) factory.init((KeyStore)null);
        else {
            KeyStore trust=KeyStore.getInstance(KeyStore.getDefaultType()); trust.load(null,null);
            try(InputStream input=Files.newInputStream(Path.of(caCert))) {
                int index=0;
                for(var certificate:CertificateFactory.getInstance("X.509").generateCertificates(input)) trust.setCertificateEntry("ca-"+index++,certificate);
                if(index==0) throw new IllegalStateException("No CA certificates");
            }
            factory.init(trust);
        }
        SSLContext context=SSLContext.getInstance("TLS"); context.init(null,factory.getTrustManagers(),null); return context;
    }
    public void publish(String topic,String payload) throws Exception {
        if(!connected()) throw new IllegalStateException("MQTT unavailable");
        MqttMessage message=new MqttMessage(payload.getBytes(StandardCharsets.UTF_8)); message.setQos(1); message.setRetained(false);
        client.publish(topic,message);
    }
    @PreDestroy public void close() {
        if(client!=null) { try { if(client.isConnected()) client.disconnect(1000); client.close(); } catch(MqttException ignored) {} }
    }
}
