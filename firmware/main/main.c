#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>
#include <math.h>
#include <stdatomic.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_sntp.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_https_ota.h"
#include "esp_ota_ops.h"
#include "esp_app_desc.h"
#include "esp_crt_bundle.h"
#include "driver/gpio.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "mqtt_client.h"
#include "cJSON.h"

static const char *TAG = "appliance";
extern const uint8_t ca_cert_pem_start[] asm("_binary_ca_cert_pem_start");
typedef struct {
    uint32_t schema;
    uint32_t revision;
    bool power;
    uint8_t speed;
    int64_t expires_epoch;
    char command_id[37];
} desired_t;
static desired_t desired = {.schema=2};
static bool output_power;
static nvs_handle_t settings;
static esp_mqtt_client_handle_t mqtt;
static SemaphoreHandle_t state_lock;
static EventGroupHandle_t network;
static char boot_id[37];
static uint32_t sequence;
static uint32_t report_sequence;
static double energy_wh;
static _Atomic bool broker_connected;

static void boot_check_failed(const char *reason) {
    ESP_LOGE(TAG,"Boot diagnostics failed: %s",reason);
    esp_ota_img_states_t state;
    if (esp_ota_get_state_partition(esp_ota_get_running_partition(),&state)==ESP_OK && state==ESP_OTA_IMG_PENDING_VERIFY) {
        esp_err_t rollback=esp_ota_mark_app_invalid_rollback_and_reboot();
        ESP_LOGE(TAG,"Rollback unavailable: %s",esp_err_to_name(rollback));
    }
    vTaskDelay(pdMS_TO_TICKS(5000));
    esp_restart();
}

static void uuid(char output[37]) {
    uint8_t bytes[16];
    esp_fill_random(bytes, sizeof(bytes));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    snprintf(output,37,"%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
             bytes[0],bytes[1],bytes[2],bytes[3],bytes[4],bytes[5],bytes[6],bytes[7],
             bytes[8],bytes[9],bytes[10],bytes[11],bytes[12],bytes[13],bytes[14],bytes[15]);
}

static void timestamp(char output[32]) {
    time_t now=time(NULL); struct tm value; gmtime_r(&now,&value);
    strftime(output,32,"%Y-%m-%dT%H:%M:%SZ",&value);
}

static time_t expiry_epoch(const char *value) {
    if (!value || time(NULL) < 1700000000) return 0;
    struct tm parsed={0};
    char *end=strptime(value,"%Y-%m-%dT%H:%M:%S",&parsed);
    if (!end) return 0;
    if (*end=='.') { end++; while (*end>='0' && *end<='9') end++; }
    if (strcmp(end,"Z")!=0 && strcmp(end,"+00:00")!=0) return 0;
    return mktime(&parsed); /* TZ is explicitly UTC below. */
}

/* Caller holds state_lock. A persisted intent may have expired before reboot. */
static bool apply_unexpired(void) {
    if (desired.expires_epoch<=time(NULL)) return false;
    ESP_ERROR_CHECK(gpio_set_level(CONFIG_APPLIANCE_OUTPUT_GPIO,desired.power ? 1 : 0));
    output_power=desired.power;
    return true;
}

static void publish(const char *suffix,cJSON *body) {
    char topic[128]; snprintf(topic,sizeof(topic),"devices/%s/%s",CONFIG_APPLIANCE_DEVICE_ID,suffix);
    char *text=cJSON_PrintUnformatted(body);
    if (text) { esp_mqtt_client_publish(mqtt,topic,text,0,1,0); free(text); }
    cJSON_Delete(body);
}

static void report(void) {
    char now[32]; timestamp(now);
    xSemaphoreTake(state_lock,portMAX_DELAY);
    cJSON *body=cJSON_CreateObject();
    cJSON_AddStringToObject(body,"device_id",CONFIG_APPLIANCE_DEVICE_ID);
    cJSON_AddStringToObject(body,"boot_id",boot_id);
    cJSON_AddNumberToObject(body,"sequence",++report_sequence);
    cJSON_AddNumberToObject(body,"revision",desired.revision);
    cJSON_AddBoolToObject(body,"power",output_power);
    cJSON_AddNumberToObject(body,"speed_percent",desired.speed);
    cJSON_AddStringToObject(body,"observed_at",now);
    cJSON_AddStringToObject(body,"firmware_version",esp_app_get_description()->version);
    if (desired.command_id[0]) cJSON_AddStringToObject(body,"command_id",desired.command_id);
    xSemaphoreGive(state_lock);
    publish("reported",body);
}

static void command(const char *payload,int length) {
    cJSON *body=cJSON_ParseWithLength(payload,length);
    if (!body) return;
    const cJSON *id=cJSON_GetObjectItemCaseSensitive(body,"device_id");
    const cJSON *cid=cJSON_GetObjectItemCaseSensitive(body,"command_id");
    const cJSON *revision=cJSON_GetObjectItemCaseSensitive(body,"revision");
    const cJSON *expires=cJSON_GetObjectItemCaseSensitive(body,"expires_at");
    const cJSON *state=cJSON_GetObjectItemCaseSensitive(body,"desired");
    const cJSON *power=cJSON_GetObjectItemCaseSensitive(state,"power");
    const cJSON *speed=cJSON_GetObjectItemCaseSensitive(state,"speed_percent");
    const time_t expiry=cJSON_IsString(expires) ? expiry_epoch(expires->valuestring) : 0;
    if (!cJSON_IsString(id) || strcmp(id->valuestring,CONFIG_APPLIANCE_DEVICE_ID) ||
        !cJSON_IsString(cid) || strlen(cid->valuestring)!=36 || !cJSON_IsNumber(revision) ||
        revision->valuedouble<0 || revision->valuedouble>UINT32_MAX || floor(revision->valuedouble)!=revision->valuedouble ||
        expiry<=time(NULL) || !cJSON_IsBool(power) ||
        !cJSON_IsNumber(speed) || speed->valuedouble<0 || speed->valuedouble>100 || floor(speed->valuedouble)!=speed->valuedouble) {
        cJSON_Delete(body); return;
    }
    bool accepted=false;
    xSemaphoreTake(state_lock,portMAX_DELAY);
    uint32_t next=(uint32_t)revision->valuedouble;
    if (next>desired.revision) {
        desired_t candidate={.schema=2,.revision=next,.power=cJSON_IsTrue(power),.speed=(uint8_t)speed->valueint,.expires_epoch=expiry};
        memcpy(candidate.command_id,cid->valuestring,36);
        esp_err_t error=nvs_set_blob(settings,"desired",&candidate,sizeof(candidate));
        if (error==ESP_OK) error=nvs_commit(settings);
        if (error==ESP_OK) {
            desired=candidate;
            accepted=apply_unexpired();
        } else ESP_LOGE(TAG,"Cannot durably accept setting: %s",esp_err_to_name(error));
    } else if (next==desired.revision && strcmp(cid->valuestring,desired.command_id)==0 &&
               desired.power==cJSON_IsTrue(power) && desired.speed==speed->valueint && desired.expires_epoch==expiry)
        accepted=apply_unexpired();
    xSemaphoreGive(state_lock);
    cJSON_Delete(body);
    if (accepted) report();
}

static void mqtt_event(void *arg,esp_event_base_t base,int32_t event_id,void *data) {
    esp_mqtt_event_handle_t event=data;
    if (event_id==MQTT_EVENT_CONNECTED) {
        broker_connected=true;
        char topic[128]; snprintf(topic,sizeof(topic),"devices/%s/desired",CONFIG_APPLIANCE_DEVICE_ID);
        esp_mqtt_client_subscribe(mqtt,topic,1);
    } else if (event_id==MQTT_EVENT_SUBSCRIBED) {
        cJSON *sync=cJSON_CreateObject();
        cJSON_AddStringToObject(sync,"device_id",CONFIG_APPLIANCE_DEVICE_ID);
        cJSON_AddStringToObject(sync,"boot_id",boot_id);
        publish("sync",sync); report();
    } else if (event_id==MQTT_EVENT_DISCONNECTED) broker_connected=false;
    else if (event_id==MQTT_EVENT_DATA) {
        /* Reject fragmented/oversized commands; reconnect sync can retry. */
        char topic[128]; snprintf(topic,sizeof(topic),"devices/%s/desired",CONFIG_APPLIANCE_DEVICE_ID);
        if (!event->retain && event->current_data_offset==0 && event->data_len==event->total_data_len && event->data_len<2048 &&
            event->topic_len==(int)strlen(topic) && !memcmp(event->topic,topic,event->topic_len)) command(event->data,event->data_len);
    }
}

static void wifi_event(void *arg,esp_event_base_t base,int32_t event_id,void *data) {
    if (base==WIFI_EVENT && event_id==WIFI_EVENT_STA_START) esp_wifi_connect();
    else if (base==WIFI_EVENT && event_id==WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(network,1); esp_wifi_connect();
    } else if (base==IP_EVENT && event_id==IP_EVENT_STA_GOT_IP) xEventGroupSetBits(network,1);
}

static void ota_task(void *arg) {
    if (!strlen(CONFIG_APPLIANCE_OTA_URL)) { vTaskDelete(NULL); return; }
#if !defined(CONFIG_SECURE_SIGNED_ON_UPDATE_NO_SECURE_BOOT)
    ESP_LOGE(TAG,"OTA disabled: build with signed-update verification first");
    vTaskDelete(NULL); return;
#endif
    if (strncmp(CONFIG_APPLIANCE_OTA_URL,"https://",8)!=0) {
        ESP_LOGE(TAG,"OTA requires HTTPS"); vTaskDelete(NULL); return;
    }
    vTaskDelay(pdMS_TO_TICKS(60000));
    esp_http_client_config_t http={.url=CONFIG_APPLIANCE_OTA_URL,.crt_bundle_attach=esp_crt_bundle_attach,.timeout_ms=20000};
#if CONFIG_APPLIANCE_OTA_USE_BROKER_CA
    http.crt_bundle_attach=NULL;
    http.cert_pem=(const char*)ca_cert_pem_start;
#endif
    esp_https_ota_config_t ota={.http_config=&http};
    esp_https_ota_handle_t handle=NULL;
    esp_err_t result=esp_https_ota_begin(&ota,&handle);
    if (result!=ESP_OK) { ESP_LOGE(TAG,"OTA download could not start"); vTaskDelete(NULL); return; }
    esp_app_desc_t incoming;
    result=esp_https_ota_get_img_desc(handle,&incoming);
    const esp_app_desc_t *running=esp_app_get_description();
    if (result!=ESP_OK || strncmp(incoming.project_name,running->project_name,sizeof(incoming.project_name))!=0 ||
        strncmp(incoming.version,running->version,sizeof(incoming.version))==0) {
        ESP_LOGW(TAG,"OTA image descriptor rejected or version already installed");
        esp_https_ota_abort(handle); vTaskDelete(NULL); return;
    }
    do { result=esp_https_ota_perform(handle); vTaskDelay(pdMS_TO_TICKS(10)); }
    while (result==ESP_ERR_HTTPS_OTA_IN_PROGRESS);
    if (result==ESP_OK && esp_https_ota_is_complete_data_received(handle)) {
        result=esp_https_ota_finish(handle);
        if (result==ESP_OK) esp_restart();
    } else esp_https_ota_abort(handle);
    ESP_LOGE(TAG,"OTA did not complete; current application retained");
    vTaskDelete(NULL);
}

void app_main(void) {
    setenv("TZ","UTC0",1); tzset();
    /* Never erase NVS automatically on a recovery error: that would lose revision fencing. */
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(nvs_open("appliance",NVS_READWRITE,&settings));
    size_t size=sizeof(desired); esp_err_t error=nvs_get_blob(settings,"desired",&desired,&size);
    if (error!=ESP_OK && error!=ESP_ERR_NVS_NOT_FOUND) ESP_ERROR_CHECK(error);
    if (desired.schema!=2 || (error==ESP_OK && size!=sizeof(desired))) abort();
    state_lock=xSemaphoreCreateMutex(); network=xEventGroupCreate(); uuid(boot_id);
    if (!state_lock || !network) abort();
    ESP_ERROR_CHECK(gpio_set_direction(CONFIG_APPLIANCE_OUTPUT_GPIO,GPIO_MODE_OUTPUT));
    /* Restore only after clock sync and only while saved intent is unexpired. */
    ESP_ERROR_CHECK(gpio_set_level(CONFIG_APPLIANCE_OUTPUT_GPIO,0));
    ESP_ERROR_CHECK(esp_netif_init()); ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta(); wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifi_event,NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,NULL));
    wifi_config_t config={0};
    strlcpy((char*)config.sta.ssid,CONFIG_APPLIANCE_WIFI_SSID,sizeof(config.sta.ssid));
    strlcpy((char*)config.sta.password,CONFIG_APPLIANCE_WIFI_PASSWORD,sizeof(config.sta.password));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA)); ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&config));
    ESP_ERROR_CHECK(esp_wifi_start());
    if (!(xEventGroupWaitBits(network,1,pdFALSE,pdTRUE,pdMS_TO_TICKS(60000)) & 1)) boot_check_failed("Wi-Fi timeout");
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL); esp_sntp_setservername(0,"pool.ntp.org"); esp_sntp_init();
    for (int attempts=0; attempts<60 && time(NULL)<1700000000; attempts++) vTaskDelay(pdMS_TO_TICKS(1000));
    if (time(NULL)<1700000000) boot_check_failed("Clock synchronization timeout");
    xSemaphoreTake(state_lock,portMAX_DELAY);
    apply_unexpired();
    xSemaphoreGive(state_lock);
    if (strncmp(CONFIG_APPLIANCE_MQTT_URI,"mqtts://",8)!=0) boot_check_failed("MQTT must use TLS");
    esp_mqtt_client_config_t broker={.broker.address.uri=CONFIG_APPLIANCE_MQTT_URI,
        .broker.verification.certificate=(const char*)ca_cert_pem_start,
        .credentials.username=CONFIG_APPLIANCE_DEVICE_ID,.credentials.client_id=CONFIG_APPLIANCE_DEVICE_ID,
        .credentials.authentication.password=CONFIG_APPLIANCE_MQTT_PASSWORD,
        .session.disable_clean_session=true,.buffer.size=2048};
    mqtt=esp_mqtt_client_init(&broker);
    if (!mqtt) abort();
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(mqtt,ESP_EVENT_ANY_ID,mqtt_event,NULL));
    ESP_ERROR_CHECK(esp_mqtt_client_start(mqtt));
    /* New image confirmation requires NVS, network, clock and broker to work. */
    for (int attempts=0; attempts<60 && !broker_connected; attempts++) vTaskDelay(pdMS_TO_TICKS(1000));
    if (!broker_connected) boot_check_failed("Broker timeout");
    esp_ota_img_states_t ota_state;
    if (esp_ota_get_state_partition(esp_ota_get_running_partition(),&ota_state)==ESP_OK && ota_state==ESP_OTA_IMG_PENDING_VERIFY)
        ESP_ERROR_CHECK(esp_ota_mark_app_valid_cancel_rollback());
    xTaskCreate(ota_task,"ota",8192,NULL,3,NULL);
    int64_t previous=esp_timer_get_time();
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(10000));
        int64_t now_us=esp_timer_get_time(); double seconds=(now_us-previous)/1000000.0; previous=now_us;
        xSemaphoreTake(state_lock,portMAX_DELAY);
        double power=2.0+(output_power ? 40.0*desired.speed/100.0 : 0.0);
        energy_wh+=power*seconds/3600.0; sequence++;
        xSemaphoreGive(state_lock);
        if (!broker_connected) continue;
        char now[32],event_id[37]; timestamp(now); uuid(event_id);
        cJSON *event=cJSON_CreateObject();
        cJSON_AddNumberToObject(event,"schema_version",1); cJSON_AddStringToObject(event,"event_id",event_id);
        cJSON_AddStringToObject(event,"device_id",CONFIG_APPLIANCE_DEVICE_ID); cJSON_AddStringToObject(event,"boot_id",boot_id);
        cJSON_AddNumberToObject(event,"sequence",sequence); cJSON_AddStringToObject(event,"event_time",now);
        cJSON_AddStringToObject(event,"source_kind","estimated"); cJSON_AddNumberToObject(event,"power_w",power);
        cJSON_AddNumberToObject(event,"energy_wh_total",energy_wh); cJSON_AddStringToObject(event,"firmware_version",esp_app_get_description()->version);
        cJSON *flags=cJSON_AddArrayToObject(event,"quality_flags");
        cJSON_AddItemToArray(flags,cJSON_CreateString("setpoint_model_no_energy_sensor"));
        cJSON_AddItemToArray(flags,cJSON_CreateString("no_durable_telemetry_spool"));
        publish("telemetry",event); report();
    }
}
