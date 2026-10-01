package dev.appliance;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;

public final class Models {
    private Models() {}
    public record Desired(@NotNull Boolean power, @NotNull @Min(0) @Max(100) Integer speedPercent) {}
    public record DeviceRequest(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") String deviceId,
                                @NotBlank @Size(max=120) String name) {}
    public record CommandRequest(@NotNull UUID commandId, @NotNull @Min(0) Long expectedRevision,
                                 @NotNull @Valid Desired desired, @NotNull Instant expiresAt) {}
    public record CommandReceipt(UUID commandId, String deviceId, long revision, String status,
                                 Desired desired, Instant expiresAt, Instant createdAt) {}
    public record DeviceSnapshot(String deviceId, String name, long desiredRevision, long reportedRevision,
                                 Desired desired, Desired reported, Instant lastSeen, String status) {}
    public record TelemetryEvent(@NotNull @Min(1) @Max(1) Integer schemaVersion,
                                 @NotNull UUID eventId,
                                 @NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") String deviceId,
                                 @NotNull UUID bootId,
                                 @NotNull @Min(0) Long sequence,
                                 @NotNull Instant eventTime,
                                 @NotBlank @Pattern(regexp="simulated|measured|estimated|public_dataset") String sourceKind,
                                 @NotNull @DecimalMin("0") Double powerW,
                                 @NotNull @DecimalMin("0") Double energyWhTotal,
                                 @NotBlank @Size(max=100) String firmwareVersion,
                                 @NotNull @Size(max=32) List<@NotBlank @Size(max=64) String> qualityFlags) {}
    public record Report(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") String deviceId,
                         @NotNull UUID bootId, @NotNull @Min(0) Long sequence,
                         @NotNull @Min(0) Long revision, @NotNull Boolean power,
                         @NotNull @Min(0) @Max(100) Integer speedPercent,
                         @NotNull Instant observedAt, @NotBlank @Size(max=100) String firmwareVersion,
                         UUID commandId) {}
    public record Sync(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") String deviceId, @NotNull UUID bootId) {}
}
