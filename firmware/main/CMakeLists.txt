idf_component_register(SRCS "main.c" INCLUDE_DIRS "." REQUIRES nvs_flash esp_wifi esp_netif mqtt json esp_https_ota app_update driver esp_timer EMBED_TXTFILES "ca_cert.pem")
