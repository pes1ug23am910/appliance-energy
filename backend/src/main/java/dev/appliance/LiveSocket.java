package dev.appliance;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Clock;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.io.IOException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;
import org.springframework.web.socket.handler.TextWebSocketHandler;

@Component
public class LiveSocket extends TextWebSocketHandler {
    private record Client(WebSocketSession session,Instant deadline,boolean authenticated) {}
    private final Map<String,Client> clients=new ConcurrentHashMap<>();
    private final OperatorAuth auth;
    private final Json json;
    private final Clock clock;
    private final long timeout;
    public LiveSocket(OperatorAuth auth,Json json,Clock clock,@Value("${app.ws-auth-timeout-seconds}") long timeout) {
        this.auth=auth; this.json=json; this.clock=clock; this.timeout=timeout;
    }
    @Override public void afterConnectionEstablished(WebSocketSession session) throws IOException {
        if(clients.size()>=128) { session.close(CloseStatus.SERVICE_OVERLOAD); return; }
        session.setTextMessageSizeLimit(4096);
        clients.put(session.getId(),new Client(new ConcurrentWebSocketSessionDecorator(session,5000,65536),clock.instant().plusSeconds(timeout),false));
    }
    @Override protected void handleTextMessage(WebSocketSession session,TextMessage message) throws IOException {
        Client client=clients.get(session.getId());
        if(client==null) { session.close(CloseStatus.POLICY_VIOLATION); return; }
        if(client.authenticated()) return;
        try {
            JsonNode frame=json.tree(message.getPayload());
            if(!clock.instant().isBefore(client.deadline()) || !"authenticate".equals(frame.path("type").asText())
                || !auth.valid(frame.path("token").asText(null))) {
                session.close(CloseStatus.POLICY_VIOLATION); clients.remove(session.getId()); return;
            }
            clients.put(session.getId(),new Client(client.session(),client.deadline(),true));
            client.session().sendMessage(new TextMessage("{\"type\":\"authenticated\"}"));
        } catch (IllegalArgumentException e) { session.close(CloseStatus.BAD_DATA); clients.remove(session.getId()); }
    }
    @Override public void afterConnectionClosed(WebSocketSession session,CloseStatus status) { clients.remove(session.getId()); }
    @Override public void handleTransportError(WebSocketSession session,Throwable error) throws IOException {
        clients.remove(session.getId()); if(session.isOpen()) session.close(CloseStatus.SERVER_ERROR);
    }
    @Scheduled(fixedDelay=500)
    public void expireUnauthenticated() {
        for(var entry:clients.entrySet()) {
            Client client=entry.getValue();
            if(!client.authenticated() && !clock.instant().isBefore(client.deadline())) close(entry.getKey(),client);
        }
    }
    private void close(String id,Client client) {
        clients.remove(id,client);
        try { client.session().close(CloseStatus.POLICY_VIOLATION); } catch(IOException ignored) {}
    }
    public void broadcast(Object event) {
        String payload=json.write(event);
        for(var entry:clients.entrySet()) {
            Client client=entry.getValue();
            if(client.authenticated() && client.session().isOpen()) {
                try { client.session().sendMessage(new TextMessage(payload)); }
                catch(Exception failure) { close(entry.getKey(),client); }
            }
        }
    }
}
