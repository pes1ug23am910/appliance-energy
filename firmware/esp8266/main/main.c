#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>
#include <math.h>
#include <stdatomic.h>
#include "../../main/tls_requirements.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_sntp.h"
#include "tcpip_adapter.h"
#include "lwip/ip_addr.h"
#include "esp_system.h"
#include "driver/gpio.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "mqtt_client.h"
#include "cJSON.h"
#include "telemetry_spool.h"
#include "desired_state.h"

#define FIRMWARE_VERSION "esp8266-0.1.0"
#define WIFI_READY 1
#define BROKER_READY 2
#define EPOCH_FLOOR INT64_C(1700000000)
static const char *TAG="appliance8266";
extern const uint8_t ca_cert_pem_start[] asm("_binary_ca_cert_pem_start");
static nvs_handle settings,spool_nvs;
static desired_store_t desired;
static telemetry_spool_t spool;
static SemaphoreHandle_t state_lock,spool_lock;
static EventGroupHandle_t network;
static esp_mqtt_client_handle_t mqtt;
static char boot_id[37];
static uint64_t sequence,report_sequence;
static double energy_wh;
static bool output_power,spool_overflow;
static int desired_subscription,receipt_subscription;
static unsigned subscriptions_ready;
static _Atomic bool send_available=true,need_sync,need_report,halted;

/* LX106 has no compiler-provided byte exchange primitive. Its single-core
 * task critical section makes this load-and-clear indivisible. */
static bool take_flag(_Atomic bool *flag) {
    taskENTER_CRITICAL();bool previous=*flag;*flag=false;taskEXIT_CRITICAL();return previous;
}
static void output(bool on) {
    if(halted)on=false;
#ifdef CONFIG_APPLIANCE_OUTPUT_ENABLED
    ESP_ERROR_CHECK(gpio_set_level(CONFIG_APPLIANCE_OUTPUT_GPIO,
#ifdef CONFIG_APPLIANCE_OUTPUT_ACTIVE_LOW
        !on
#else
        on
#endif
    ));
#endif
    output_power=on;
}
static void fail_closed(const char *reason) {
    halted=true; if(state_lock)xSemaphoreTake(state_lock,portMAX_DELAY);
    output(false); if(state_lock)xSemaphoreGive(state_lock);
    ESP_LOGE(TAG,"Stopped: %s",reason);
    vTaskDelay(pdMS_TO_TICKS(3000)); esp_restart();
}
static int setting_read(void *ctx,uint8_t *p,size_t *n) {
    (void)ctx;esp_err_t e=nvs_get_blob(settings,"desired_v1",p,n);
    return e==ESP_OK?0:e==ESP_ERR_NVS_NOT_FOUND?1:-1;
}
static int setting_write(void *ctx,const uint8_t *p,size_t n) {
    (void)ctx;esp_err_t e=nvs_set_blob(settings,"desired_v1",p,n);
    if(e==ESP_OK)e=nvs_commit(settings);
    return e==ESP_OK?0:-1;
}
static int spool_read_storage(void *ctx,unsigned slot,uint8_t *p,size_t *n) {
    (void)ctx;char key[8];snprintf(key,sizeof(key),"t%03u",slot);
    esp_err_t e=nvs_get_blob(spool_nvs,key,p,n);return e==ESP_OK?0:e==ESP_ERR_NVS_NOT_FOUND?1:-1;
}
static int spool_write_storage(void *ctx,unsigned slot,const uint8_t *p,size_t n) {
    (void)ctx;char key[8];snprintf(key,sizeof(key),"t%03u",slot);
    esp_err_t e=nvs_set_blob(spool_nvs,key,p,n);if(e==ESP_OK)e=nvs_commit(spool_nvs);return e==ESP_OK?0:-1;
}
static int spool_erase_storage(void *ctx,unsigned slot) {
    (void)ctx;char key[8];snprintf(key,sizeof(key),"t%03u",slot);
    esp_err_t e=nvs_erase_key(spool_nvs,key);if(e==ESP_OK)e=nvs_commit(spool_nvs);return e==ESP_OK?0:-1;
}
static void uuid(char out[37]) {
    uint8_t b[16]; for(unsigned i=0;i<16;i+=4){uint32_t r=esp_random();memcpy(b+i,&r,4);}
    b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;
    snprintf(out,37,"%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7],b[8],b[9],b[10],b[11],b[12],b[13],b[14],b[15]);
}
static void timestamp(char out[32]) {time_t now=time(NULL);struct tm tm;gmtime_r(&now,&tm);strftime(out,32,"%Y-%m-%dT%H:%M:%SZ",&tm);}
static int64_t expiry_epoch(const char *s) {
    if(!s || time(NULL)<EPOCH_FLOOR)return 0;
    struct tm t={0};char *end=strptime(s,"%Y-%m-%dT%H:%M:%S",&t);
    if(!end)return 0;
    if(*end=='.'){end++;if(*end<'0'||*end>'9')return 0;while(*end>='0'&&*end<='9')end++;}
    if(strcmp(end,"Z") && strcmp(end,"+00:00"))return 0;
    return mktime(&t);
}
static bool integer(const cJSON *v,double maximum) {return cJSON_IsNumber(v)&&isfinite(v->valuedouble)&&v->valuedouble>=0&&v->valuedouble<=maximum&&floor(v->valuedouble)==v->valuedouble;}
static cJSON *parse_message(const char *payload,int length) {
    if(length<=0 || length>=1536 || memchr(payload,0,(size_t)length))return NULL;
    char *text=malloc((size_t)length+1);if(!text)return NULL;
    memcpy(text,payload,(size_t)length);text[length]=0;
    cJSON *body=cJSON_ParseWithOpts(text,NULL,true);free(text);return body;
}
static void command(const char *payload,int length) {
    cJSON *b=parse_message(payload,length);if(!b)return;
    const cJSON *id=cJSON_GetObjectItemCaseSensitive(b,"device_id"),*cid=cJSON_GetObjectItemCaseSensitive(b,"command_id"),*rev=cJSON_GetObjectItemCaseSensitive(b,"revision");
    const cJSON *expiry=cJSON_GetObjectItemCaseSensitive(b,"expires_at"),*state=cJSON_GetObjectItemCaseSensitive(b,"desired");
    const cJSON *power=cJSON_GetObjectItemCaseSensitive(state,"power"),*speed=cJSON_GetObjectItemCaseSensitive(state,"speed_percent");
    if(!cJSON_IsString(id)||strcmp(id->valuestring,CONFIG_APPLIANCE_DEVICE_ID)||!cJSON_IsString(cid)||!desired_uuid_valid(cid->valuestring)||!integer(rev,(double)DESIRED_MAX_REVISION)||!cJSON_IsBool(power)||!integer(speed,100)||!cJSON_IsString(expiry)){cJSON_Delete(b);return;}
    desired_value_t next={.revision=(uint64_t)rev->valuedouble,.expires_epoch=expiry_epoch(expiry->valuestring),.power=cJSON_IsTrue(power),.speed=(uint8_t)speed->valueint};
    memcpy(next.command_id,cid->valuestring,37);
    xSemaphoreTake(state_lock,portMAX_DELAY);
    desired_result_t result=halted ? DESIRED_IO : desired_accept(&desired,&next,time(NULL));
    /* A commit can consume the remaining deadline; check again before actuation. */
    if(result==DESIRED_ACCEPTED && desired_restorable(&desired,time(NULL))){output(next.power);need_report=true;}
    xSemaphoreGive(state_lock);cJSON_Delete(b);
    if(result==DESIRED_IO)fail_closed("setting commit uncertain; restart required");
}
static void receipt(const char *payload,int length) {
    cJSON *b=parse_message(payload,length);if(!b)return;
    const cJSON *id=cJSON_GetObjectItemCaseSensitive(b,"event_id"),*status=cJSON_GetObjectItemCaseSensitive(b,"status");
    spool_result_t result=SPOOL_ABSENT;
    if(cJSON_IsString(id)&&cJSON_IsString(status)&&!strcmp(status->valuestring,"accepted")) {
        xSemaphoreTake(spool_lock,portMAX_DELAY);result=spool_accept(&spool,id->valuestring);xSemaphoreGive(spool_lock);
    }
    cJSON_Delete(b);if(result==SPOOL_IO)fail_closed("receipt commit uncertain; restart required");
}
static void mqtt_event(void *arg,esp_event_base_t base,int32_t event_id,void *data) {
    (void)arg;(void)base;esp_mqtt_event_handle_t e=data;
    if(event_id==MQTT_EVENT_CONNECTED) {
        subscriptions_ready=0;xEventGroupClearBits(network,BROKER_READY);
        char topic[128];snprintf(topic,sizeof(topic),"devices/%s/desired",CONFIG_APPLIANCE_DEVICE_ID);desired_subscription=esp_mqtt_client_subscribe(mqtt,topic,1);
        snprintf(topic,sizeof(topic),"devices/%s/receipt",CONFIG_APPLIANCE_DEVICE_ID);receipt_subscription=esp_mqtt_client_subscribe(mqtt,topic,1);
        if(desired_subscription<0 || receipt_subscription<0)fail_closed("MQTT subscription allocation failed");
    } else if(event_id==MQTT_EVENT_DISCONNECTED)xEventGroupClearBits(network,BROKER_READY);
    else if(event_id==MQTT_EVENT_PUBLISHED)send_available=true;
    else if(event_id==MQTT_EVENT_SUBSCRIBED) {
        if(e->msg_id==desired_subscription)subscriptions_ready|=1;
        if(e->msg_id==receipt_subscription)subscriptions_ready|=2;
        if(subscriptions_ready==3){xEventGroupSetBits(network,BROKER_READY);need_sync=true;need_report=true;}
    }
    else if(event_id==MQTT_EVENT_DATA && !e->retain && e->current_data_offset==0 && e->data_len==e->total_data_len && e->data_len>0 && e->data_len<1536) {
        char topic[128];snprintf(topic,sizeof(topic),"devices/%s/desired",CONFIG_APPLIANCE_DEVICE_ID);
        if(e->topic_len==(int)strlen(topic)&&!memcmp(e->topic,topic,e->topic_len))command(e->data,e->data_len);
        snprintf(topic,sizeof(topic),"devices/%s/receipt",CONFIG_APPLIANCE_DEVICE_ID);
        if(e->topic_len==(int)strlen(topic)&&!memcmp(e->topic,topic,e->topic_len))receipt(e->data,e->data_len);
    }
}
/* Only the application task publishes. One QoS1 PUBLISH at a time bounds RAM.
 * PUBACK frees this transport window; it never deletes durable telemetry. */
static bool publish_text(const char *suffix,const char *text) {
    if(halted || !(xEventGroupGetBits(network)&BROKER_READY)||!take_flag(&send_available))return false;
    char topic[128];snprintf(topic,sizeof(topic),"devices/%s/%s",CONFIG_APPLIANCE_DEVICE_ID,suffix);
    if(esp_mqtt_client_publish(mqtt,topic,text,0,1,0)<0){/* Delivery/queueing is ambiguous: retain the window until ACK or reboot. */return false;}return true;
}
static bool publish_json(const char *suffix,cJSON *b) {
    char *text=cJSON_PrintUnformatted(b);cJSON_Delete(b);if(!text)fail_closed("JSON allocation");
    bool ok=publish_text(suffix,text);free(text);return ok;
}
static bool report(void) {
    if(report_sequence==DESIRED_MAX_REVISION)fail_closed("report sequence exhausted");
    char now[32];timestamp(now);cJSON *b=cJSON_CreateObject();
    xSemaphoreTake(state_lock,portMAX_DELAY);
    cJSON_AddStringToObject(b,"device_id",CONFIG_APPLIANCE_DEVICE_ID);cJSON_AddStringToObject(b,"boot_id",boot_id);
    cJSON_AddNumberToObject(b,"sequence",++report_sequence);cJSON_AddNumberToObject(b,"revision",(double)desired.value.revision);
    cJSON_AddBoolToObject(b,"power",output_power);cJSON_AddNumberToObject(b,"speed_percent",desired.value.speed);
    cJSON_AddStringToObject(b,"observed_at",now);cJSON_AddStringToObject(b,"firmware_version",FIRMWARE_VERSION);
    if(desired.value.command_id[0])cJSON_AddStringToObject(b,"command_id",desired.value.command_id);
    xSemaphoreGive(state_lock);return publish_json("reported",b);
}
static void sample(double seconds) {
    if(sequence==DESIRED_MAX_REVISION)fail_closed("telemetry sequence exhausted");
    xSemaphoreTake(state_lock,portMAX_DELAY);double power=2.0+(output_power?40.0*desired.value.speed/100.0:0.0);energy_wh+=power*seconds/3600.0;xSemaphoreGive(state_lock);
    char now[32],id[37];timestamp(now);uuid(id);cJSON *b=cJSON_CreateObject();
    cJSON_AddNumberToObject(b,"schema_version",1);cJSON_AddStringToObject(b,"event_id",id);cJSON_AddStringToObject(b,"device_id",CONFIG_APPLIANCE_DEVICE_ID);cJSON_AddStringToObject(b,"boot_id",boot_id);
    cJSON_AddNumberToObject(b,"sequence",(double)++sequence);cJSON_AddStringToObject(b,"event_time",now);cJSON_AddStringToObject(b,"source_kind","estimated");
    cJSON_AddNumberToObject(b,"power_w",power);cJSON_AddNumberToObject(b,"energy_wh_total",energy_wh);cJSON_AddStringToObject(b,"firmware_version",FIRMWARE_VERSION);
    cJSON *flags=cJSON_AddArrayToObject(b,"quality_flags");cJSON_AddItemToArray(flags,cJSON_CreateString("setpoint_model_no_energy_sensor"));
#ifndef CONFIG_APPLIANCE_OUTPUT_ENABLED
    cJSON_AddItemToArray(flags,cJSON_CreateString("gpio_output_disabled"));
#endif
    if(spool_overflow)cJSON_AddItemToArray(flags,cJSON_CreateString("telemetry_spool_capacity_exceeded"));
    char *text=cJSON_PrintUnformatted(b);cJSON_Delete(b);if(!text)fail_closed("JSON allocation");
    xSemaphoreTake(spool_lock,portMAX_DELAY);spool_result_t r=spool_append(&spool,id,text);xSemaphoreGive(spool_lock);free(text);
    if(r==SPOOL_IO||r==SPOOL_INVALID)fail_closed("telemetry persistence");
    spool_overflow=r==SPOOL_FULL;if(spool_overflow)ESP_LOGW(TAG,"Spool full: sample skipped; unacknowledged records retained");
    need_report=true;
}
static void replay_one(void) {
    static unsigned cursor;char text[SPOOL_PAYLOAD_MAX];spool_result_t r=SPOOL_ABSENT;
    xSemaphoreTake(spool_lock,portMAX_DELAY);
    for(unsigned n=0;n<SPOOL_CAPACITY && r==SPOOL_ABSENT;n++){r=spool_read(&spool,cursor,text,sizeof(text));cursor=(cursor+1)%SPOOL_CAPACITY;}
    xSemaphoreGive(spool_lock);
    if(r==SPOOL_IO)fail_closed("spool read");
    if(r==SPOOL_OK)publish_text("telemetry",text);
}
static void clock_sync_notification(struct timeval *tv) {
    ESP_LOGI(TAG,"Clock update received: epoch=%ld",(long)tv->tv_sec);
}
static void clock_diagnostics(void) {
    tcpip_adapter_dns_info_t dns;
    char address[48];
    if(tcpip_adapter_get_dns_info(TCPIP_ADAPTER_IF_STA,TCPIP_ADAPTER_DNS_MAIN,&dns)==ESP_OK &&
       ipaddr_ntoa_r(&dns.ip,address,sizeof(address)))
        ESP_LOGI(TAG,"Clock DNS server: %s",address);
    ESP_LOGI(TAG,"Clock startup free heap: %u",(unsigned)esp_get_free_heap_size());
}
static void wifi_event(void *arg,esp_event_base_t base,int32_t event_id,void *data) {
    (void)arg;(void)data;
    if(base==WIFI_EVENT&&event_id==WIFI_EVENT_STA_START)esp_wifi_connect();
    else if(base==WIFI_EVENT&&event_id==WIFI_EVENT_STA_DISCONNECTED){xEventGroupClearBits(network,WIFI_READY);esp_wifi_connect();}
    else if(base==IP_EVENT&&event_id==IP_EVENT_STA_GOT_IP)xEventGroupSetBits(network,WIFI_READY);
}
void app_main(void) {
    setenv("TZ","UTC0",1);tzset();
#ifdef CONFIG_APPLIANCE_OUTPUT_ENABLED
    /* Set the inactive latch before changing pin direction. */
    output(false);ESP_ERROR_CHECK(gpio_set_direction(CONFIG_APPLIANCE_OUTPUT_GPIO,GPIO_MODE_OUTPUT));
#endif
    ESP_ERROR_CHECK(nvs_flash_init());ESP_ERROR_CHECK(nvs_flash_init_partition("telemetry"));
    ESP_ERROR_CHECK(nvs_open("appliance",NVS_READWRITE,&settings));ESP_ERROR_CHECK(nvs_open_from_partition("telemetry","spool",NVS_READWRITE,&spool_nvs));
    if(!desired_open(&desired,NULL,setting_read,setting_write)||spool_open(&spool,(spool_storage_t){.read=spool_read_storage,.write=spool_write_storage,.erase=spool_erase_storage})!=SPOOL_OK)fail_closed("stored data corrupt or unreadable; never auto erase");
    state_lock=xSemaphoreCreateMutex();spool_lock=xSemaphoreCreateMutex();network=xEventGroupCreate();if(!state_lock||!spool_lock||!network)fail_closed("mutex allocation");
    if(strncmp(CONFIG_APPLIANCE_MQTT_URI,"mqtts://",8)||!strlen(CONFIG_APPLIANCE_WIFI_SSID)||!strlen(CONFIG_APPLIANCE_MQTT_PASSWORD))fail_closed("configure Wi-Fi, TLS broker and unique credentials locally");
    ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifi_event,NULL));ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,NULL));
    wifi_config_t config={0};strlcpy((char*)config.sta.ssid,CONFIG_APPLIANCE_WIFI_SSID,sizeof(config.sta.ssid));strlcpy((char*)config.sta.password,CONFIG_APPLIANCE_WIFI_PASSWORD,sizeof(config.sta.password));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&config));ESP_ERROR_CHECK(esp_wifi_start());
    if(!(xEventGroupWaitBits(network,WIFI_READY,pdFALSE,pdTRUE,pdMS_TO_TICKS(60000))&WIFI_READY))fail_closed("Wi-Fi timeout");
    clock_diagnostics();
    sntp_set_time_sync_notification_cb(clock_sync_notification);
    sntp_setoperatingmode(SNTP_OPMODE_POLL);sntp_setservername(0,CONFIG_APPLIANCE_NTP_SERVER);sntp_init();
    for(unsigned n=0;n<60&&time(NULL)<EPOCH_FLOOR;n++) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        if((n+1)%15==0)ESP_LOGI(TAG,"Clock wait: seconds=%u epoch=%ld status=%d free_heap=%u",n+1,(long)time(NULL),(int)sntp_get_sync_status(),(unsigned)esp_get_free_heap_size());
    }
    if(time(NULL)<EPOCH_FLOOR)fail_closed("clock synchronization timeout");
    uuid(boot_id);xSemaphoreTake(state_lock,portMAX_DELAY);if(desired_restorable(&desired,time(NULL)))output(desired.value.power);xSemaphoreGive(state_lock);
    esp_mqtt_client_config_t broker={.uri=CONFIG_APPLIANCE_MQTT_URI,.cert_pem=(const char*)ca_cert_pem_start,.username=CONFIG_APPLIANCE_DEVICE_ID,.client_id=CONFIG_APPLIANCE_DEVICE_ID,.password=CONFIG_APPLIANCE_MQTT_PASSWORD,.disable_clean_session=true,.buffer_size=1536,.task_stack=6144,.skip_cert_common_name_check=false};
    mqtt=esp_mqtt_client_init(&broker);if(!mqtt)fail_closed("MQTT allocation");ESP_ERROR_CHECK(esp_mqtt_client_register_event(mqtt,ESP_EVENT_ANY_ID,mqtt_event,NULL));ESP_ERROR_CHECK(esp_mqtt_client_start(mqtt));
    TickType_t last_sample=xTaskGetTickCount(),last_progress=last_sample;
    while(true) {
        vTaskDelay(pdMS_TO_TICKS(1000));TickType_t tick=xTaskGetTickCount();
        if((TickType_t)(tick-last_sample)>=pdMS_TO_TICKS(10000)){sample((double)(TickType_t)(tick-last_sample)/configTICK_RATE_HZ);last_sample=tick;}
        if(send_available)last_progress=tick;
        else if((TickType_t)(tick-last_progress)>pdMS_TO_TICKS(120000))fail_closed("MQTT acknowledgement timeout; durable records retained");
        if(!(xEventGroupGetBits(network)&BROKER_READY)||!send_available)continue;
        if(take_flag(&need_sync)) {
            cJSON *b=cJSON_CreateObject();cJSON_AddStringToObject(b,"device_id",CONFIG_APPLIANCE_DEVICE_ID);cJSON_AddStringToObject(b,"boot_id",boot_id);if(!publish_json("sync",b))need_sync=true;
        } else if(take_flag(&need_report)){if(!report())need_report=true;}
        else replay_one();
    }
}



