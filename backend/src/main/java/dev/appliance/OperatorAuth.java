package dev.appliance;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(10)
public class OperatorAuth extends OncePerRequestFilter {
    private final byte[] token;
    public OperatorAuth(@Value("${app.api-token}") String token) {
        if(token==null || token.length()<16) throw new IllegalStateException("API_TOKEN must contain at least 16 characters");
        this.token=token.getBytes(StandardCharsets.UTF_8);
    }
    public boolean valid(String supplied) {
        return supplied!=null && MessageDigest.isEqual(token,supplied.getBytes(StandardCharsets.UTF_8));
    }
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain) throws ServletException,IOException {
        String path=request.getRequestURI();
        if(!"OPTIONS".equals(request.getMethod()) && !path.equals("/actuator/health") && !path.equals("/ws")) {
            String header=request.getHeader("Authorization");
            if(header==null || !header.startsWith("Bearer ") || !valid(header.substring(7))) {
                response.setStatus(401); response.setContentType("application/json"); response.getWriter().write("{\"error\":\"Unauthorized\"}"); return;
            }
        }
        chain.doFilter(request,response);
    }
}
