package dev.appliance;

import static dev.appliance.Models.*;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

@Component
public class MqttIngress {
    private static final Pattern TOPIC=Pattern.compile("devices/([A-Za-z0-9_-]{1,64})/(telemetry|reported|sync)");
    private final DeviceService service;
    private final Json json;
    public MqttIngress(DeviceService service,Json json) { this.service=service; this.json=json; }
    public void rejectRetained(String topic,String payload) { service.quarantine(topic,payload,"Retained device message rejected"); }
    public void accept(String topic,String payload) {
        try {
            if(payload.length()>65536) throw new ApiException(400,"Payload exceeds limit");
            var match=TOPIC.matcher(topic);
            if(!match.matches()) throw new ApiException(400,"Invalid topic");
            switch(match.group(2)) {
                case "telemetry" -> service.telemetry(match.group(1),json.read(payload,TelemetryEvent.class));
                case "reported" -> service.report(match.group(1),json.read(payload,Report.class));
                case "sync" -> service.sync(match.group(1),json.read(payload,Sync.class));
                default -> throw new ApiException(400,"Unsupported topic");
            }
        } catch(ApiException | IllegalArgumentException invalid) {
            service.quarantine(topic,payload,invalid.getMessage());
        }
    }
}
