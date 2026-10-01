"""Exercise the patched upstream delivery function, with stubbed transport/parser.

The test compiles the actual function from the pinned SDK. It checks RETAIN
across fragmented delivery and message boundaries; it is not a network test.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

sdk = Path(os.environ['IDF_PATH'])
mqtt = sdk / 'components/mqtt/esp-mqtt'
assert subprocess.check_output(['git', '-C', str(mqtt), 'rev-parse', 'HEAD'], text=True).strip() == '01594bf118ae502b5a0ead040446f2be75d26223'
source = (mqtt / 'mqtt_client.c').read_text()
function = source[source.index('static esp_err_t deliver_publish('):source.index('static bool is_valid_mqtt_msg(')]
header = (mqtt / 'include/mqtt_client.h').read_text()
assert re.search(r'int\s+retain;', header), 'patched event must expose RETAIN'
helpers = (mqtt / 'lib/include/mqtt_msg.h').read_text()
retain = re.search(r'static inline int mqtt_get_retain\(.*?\n\}', helpers, re.S).group(0)
prefix = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
#define ESP_OK 0
#define ESP_FAIL -1
#define MQTT_EVENT_DATA 5
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
typedef int esp_err_t;
typedef struct {int msg_id,total_data_len,retain,event_id,data_len,current_data_offset,topic_len; char *data,*topic;} event_t;
typedef struct client {struct {uint8_t *in_buffer;size_t in_buffer_read_len,message_length,in_buffer_length;} mqtt_state;event_t event;void *transport;struct {int network_timeout_ms;} *config;} *esp_mqtt_client_handle_t;
static event_t seen[4];static unsigned count;static int fill_byte,read_failure;
static char *mqtt_get_publish_topic(uint8_t *b,size_t *n){(void)b;if(*n<7)return NULL;*n=1;return "t";}
static char *mqtt_get_publish_data(uint8_t *b,size_t *n){*n-=7;return (char*)b+7;}
static int mqtt_get_id(uint8_t *b,size_t n){(void)b;(void)n;return 123;}
static int esp_mqtt_dispatch_event(esp_mqtt_client_handle_t c){assert(count<4);seen[count++]=c->event;return 0;}
static int esp_transport_read(void *t,char *b,size_t n,int timeout){(void)t;(void)timeout;if(read_failure)return -1;memset(b,fill_byte,n);return (int)n;}
'''
suffix = r'''
int main(void){
    uint8_t buffer[32];struct client c={0};struct {int network_timeout_ms;} cfg={1};
    c.config=(void*)&cfg;c.mqtt_state.in_buffer=buffer;c.mqtt_state.in_buffer_length=8;
    for(int retained=1;retained>=0;retained--){
        memset(buffer,0,sizeof(buffer));buffer[0]=0x32|retained;fill_byte=!retained;count=0;
        c.mqtt_state.in_buffer_read_len=13;c.mqtt_state.message_length=23;
        assert(deliver_publish(&c)==ESP_OK);assert(count==3);
        for(unsigned i=0;i<count;i++){assert(seen[i].retain==retained);assert(seen[i].total_data_len==16);}
        assert(seen[0].current_data_offset==0&&seen[0].data_len==6&&seen[0].topic_len==1);
        assert(seen[1].current_data_offset==6&&seen[1].data_len==8&&seen[1].topic==NULL);
        assert(seen[2].current_data_offset==14&&seen[2].data_len==2&&seen[2].topic==NULL);
    }
    puts("PASS RETAIN survives continuation buffer overwrite and resets for next message");
    count=0;buffer[0]=0x31;read_failure=1;c.mqtt_state.in_buffer_read_len=13;c.mqtt_state.message_length=23;
    assert(deliver_publish(&c)==ESP_FAIL&&count==1&&seen[0].retain==1);
    read_failure=0;count=0;c.mqtt_state.in_buffer_read_len=2;c.mqtt_state.message_length=23;
    assert(deliver_publish(&c)==ESP_FAIL&&count==0);
    puts("PASS transport interruption and malformed header do not complete delivery");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='mqtt-retain-') as directory:
    path = Path(directory)
    (path / 'test.c').write_text(prefix + retain + '\n' + function + suffix)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
