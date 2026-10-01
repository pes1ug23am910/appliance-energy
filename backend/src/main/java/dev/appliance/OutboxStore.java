package dev.appliance;

import java.time.Clock;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class OutboxStore {
    public record Claim(long id,String kind,String deviceId,String key,String payload,int attempt) {}
    private final JdbcTemplate db;
    private final DeviceService service;
    private final Clock clock;
    public OutboxStore(JdbcTemplate db,DeviceService service,Clock clock) { this.db=db; this.service=service; this.clock=clock; }
    @Transactional
    public Claim claim(boolean mqtt,boolean kafka) {
        String kinds=mqtt ? kafka ? "'desired','receipt','telemetry'" : "'desired','receipt'" : kafka ? "'telemetry'" : "'none'";
        var rows=db.query("SELECT id,kind,device_id,dedup_key,payload::text,attempts FROM outbox WHERE published_at IS NULL AND available_at<=now() AND kind IN ("+kinds+") ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED",
            (rs,n)->new Claim(rs.getLong("id"),rs.getString("kind"),rs.getString("device_id"),rs.getString("dedup_key"),rs.getString("payload"),rs.getInt("attempts")+1));
        if(rows.isEmpty()) return null;
        Claim claim=rows.getFirst();
        if("desired".equals(claim.kind())) {
            var command=service.stored(UUID.fromString(claim.key())).orElseThrow();
            var device=service.device(claim.deviceId());
            if(!command.expiresAt().isAfter(clock.instant()) || command.revision()!=device.desiredRevision()
                || Set.of("expired","superseded","rejected").contains(command.status())) {
                db.update("UPDATE outbox SET published_at=now(),last_error='Intent no longer deliverable' WHERE id=?",claim.id());
                return null;
            }
            db.update("UPDATE commands SET attempted_at=COALESCE(attempted_at,now()) WHERE command_id=?",command.commandId());
        }
        db.update("UPDATE outbox SET attempts=attempts+1,available_at=now()+interval '30 seconds' WHERE id=?",claim.id());
        return claim;
    }
    @Transactional
    public void delivered(Claim claim) {
        db.update("UPDATE outbox SET published_at=now(),last_error=NULL WHERE id=? AND attempts=?",claim.id(),claim.attempt());
        if("desired".equals(claim.kind())) {
            int changed=db.update("UPDATE commands SET status='awaiting_device' WHERE command_id=? AND status='accepted'",UUID.fromString(claim.key()));
            if(changed>0) service.changed(null,UUID.fromString(claim.key()));
        }
    }
    public void failed(Claim claim,Exception failure) {
        db.update("UPDATE outbox SET available_at=now()+interval '2 seconds',last_error=? WHERE id=? AND attempts=?",
            failure.getClass().getSimpleName(),claim.id(),claim.attempt());
    }
    @Transactional
    public void expireCommands() {
        var expired=db.queryForList("UPDATE commands SET status=CASE WHEN attempted_at IS NULL THEN 'expired' ELSE 'outcome_unknown' END WHERE status IN ('accepted','awaiting_device') AND expires_at<=? RETURNING command_id",
            UUID.class,DeviceService.ts(clock.instant()));
        expired.forEach(id->service.changed(null,id));
    }
}
