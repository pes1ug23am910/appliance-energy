package dev.appliance;

import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.*;
import org.springframework.web.cors.*;
import org.springframework.web.filter.CorsFilter;
import org.springframework.web.socket.config.annotation.*;

@Configuration
@EnableWebSocket
public class WebConfig implements WebSocketConfigurer {
    private final LiveSocket socket;
    private final List<String> origins;
    public WebConfig(LiveSocket socket,@Value("${API_ALLOWED_ORIGINS:http://localhost:8090,http://127.0.0.1:8090,http://localhost:18081,http://127.0.0.1:18081}") List<String> origins) {
        this.socket=socket; this.origins=origins;
    }
    @Override public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(socket,"/ws").setAllowedOrigins(origins.toArray(String[]::new));
    }
    @Bean FilterRegistrationBean<CorsFilter> cors() {
        CorsConfiguration config=new CorsConfiguration();
        config.setAllowedOrigins(origins); config.setAllowedMethods(List.of("GET","POST","OPTIONS"));
        config.setAllowedHeaders(List.of("Authorization","Content-Type")); config.setMaxAge(3600L);
        UrlBasedCorsConfigurationSource source=new UrlBasedCorsConfigurationSource(); source.registerCorsConfiguration("/api/**",config);
        FilterRegistrationBean<CorsFilter> registration=new FilterRegistrationBean<>(new CorsFilter(source)); registration.setOrder(0); return registration;
    }
}
