package dev.appliance;

import static dev.appliance.Models.*;
import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import java.util.List;
import java.util.UUID;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class ApiController {
    private final DeviceService service;
    public ApiController(DeviceService service) { this.service=service; }
    @GetMapping("/devices") public List<DeviceSnapshot> devices() { return service.devices(); }
    @PostMapping("/devices") public DeviceSnapshot create(@Valid @RequestBody DeviceRequest request) { return service.register(request); }
    @GetMapping("/devices/{id}") public DeviceSnapshot device(@PathVariable String id) { return service.device(id); }
    @PostMapping("/devices/{id}/commands") public CommandReceipt submit(@PathVariable String id,@Valid @RequestBody CommandRequest command) { return service.submit(id,command); }
    @GetMapping("/commands/{id}") public CommandReceipt command(@PathVariable UUID id) { return service.command(id); }
    @GetMapping("/devices/{id}/telemetry") public List<JsonNode> telemetry(@PathVariable String id,@RequestParam(defaultValue="100") int limit) { return service.telemetry(id,limit); }
}
