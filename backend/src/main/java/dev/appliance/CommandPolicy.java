package dev.appliance;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Objects;
import dev.appliance.Models.CommandRequest;

public final class CommandPolicy {
    private CommandPolicy() {}
    public static Instant precision(Instant value) { return value.truncatedTo(ChronoUnit.MICROS); }
    public static boolean equivalent(String deviceId, CommandRequest request, StoredCommand stored) {
        return deviceId.equals(stored.deviceId())
            && Objects.equals(request.expectedRevision(),stored.expectedRevision())
            && Objects.equals(request.desired().power(),stored.power())
            && Objects.equals(request.desired().speedPercent(),stored.speedPercent())
            && precision(request.expiresAt()).equals(stored.expiresAt());
    }
    public static String expiredStatus(Instant attemptedAt) { return attemptedAt==null ? "expired" : "outcome_unknown"; }
    public record StoredCommand(java.util.UUID commandId, String deviceId, long expectedRevision,
                                long revision, boolean power, int speedPercent, Instant expiresAt,
                                Instant createdAt, Instant attemptedAt, String status) {
        public Models.CommandReceipt receipt() {
            return new Models.CommandReceipt(commandId,deviceId,revision,status,
                new Models.Desired(power,speedPercent),expiresAt,createdAt);
        }
    }
}
