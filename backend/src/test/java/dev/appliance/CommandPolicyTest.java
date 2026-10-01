package dev.appliance;

import static org.junit.jupiter.api.Assertions.*;
import dev.appliance.Models.*;
import dev.appliance.CommandPolicy.StoredCommand;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class CommandPolicyTest {
    @Test void equivalenceIncludesRevisionDeviceStateAndExpiry() {
        UUID id=UUID.randomUUID(); Instant expiry=Instant.parse("2026-01-01T00:00:00.123456Z");
        StoredCommand stored=new StoredCommand(id,"one",2,3,true,50,expiry,expiry,null,"accepted");
        assertTrue(CommandPolicy.equivalent("one",new CommandRequest(id,2L,new Desired(true,50),expiry),stored));
        assertFalse(CommandPolicy.equivalent("two",new CommandRequest(id,2L,new Desired(true,50),expiry),stored));
        assertFalse(CommandPolicy.equivalent("one",new CommandRequest(id,3L,new Desired(true,50),expiry),stored));
        assertFalse(CommandPolicy.equivalent("one",new CommandRequest(id,2L,new Desired(false,50),expiry),stored));
        assertFalse(CommandPolicy.equivalent("one",new CommandRequest(id,2L,new Desired(true,50),expiry.plusSeconds(1)),stored));
    }
    @Test void dispatchedTimeoutIsAnUnknownOutcome() {
        assertEquals("expired",CommandPolicy.expiredStatus(null));
        assertEquals("outcome_unknown",CommandPolicy.expiredStatus(Instant.EPOCH));
    }
}
