"""Exercise pinned MQTT delivery and SUBACK handling with stubbed transport.

The test compiles the actual function from the pinned SDK. It checks RETAIN
across fragmented delivery and message boundaries, plus SUBACK rejection through
the real packet receiver and parser. It is not a network test.
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
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True, timeout=15)


# SUBACK must acknowledge one subscription successfully before the app can use it.
# Compile the actual upstream receiver, processor, request validator and parsers;
# only transport, outbox storage and unrelated PUBLISH paths are stubbed.
parser = (mqtt / 'lib/mqtt_msg.c').read_text()
def between(text, start, end):
    # Skip forward declarations when extracting an upstream function body.
    offset = (re.search(re.escape(start) + r'[^;{}]*\n\{', text).start()
              if start.endswith('(') else text.index(start))
    return text[offset:text.index(end, offset + len(start))]

suback_prefix = r"""
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGV(...) ((void)0)
#define MQTT_EVENT_SUBSCRIBED 1
#define MQTT_EVENT_UNSUBSCRIBED 2
#define MQTT_EVENT_PUBLISHED 3
#define CONFIRMED 1
#define ACKNOWLEDGED 2
typedef int esp_err_t;
typedef void *esp_transport_handle_t;
typedef struct {size_t length;} mqtt_message_t;
typedef struct {int event_id,msg_id;} suback_event_t;
typedef struct client {
    struct {
        uint8_t *in_buffer;
        int in_buffer_read_len,message_length,in_buffer_length;
        int pending_msg_id,pending_msg_count,mqtt_connection;
        mqtt_message_t *outbound_message;
    } mqtt_state;
    suback_event_t event;
    void *transport,*outbox;
    bool wait_for_ping_resp;
} *esp_mqtt_client_handle_t;
static uint8_t wire[32];
static size_t wire_length,wire_position,read_chunk;
static bool eof_error;
static unsigned event_count,delete_count,error_count,pending_mask;
static int last_event_id;
static int esp_transport_read(void *t,char *buffer,size_t length,int timeout){
    (void)t;(void)timeout;
    if(wire_position==wire_length)return eof_error?-1:0;
    if(length>wire_length-wire_position)length=wire_length-wire_position;
    if(length>read_chunk)length=read_chunk;
    memcpy(buffer,wire+wire_position,length);wire_position+=length;return (int)length;
}
static void esp_mqtt_client_dispatch_tls_error(esp_mqtt_client_handle_t c){(void)c;error_count++;}
static int outbox_delete(void *o,int id,int type){
    (void)o;unsigned bit=id==17?1:(id==29?2:0);
    if(type!=8||!(pending_mask&bit))return ESP_FAIL;
    pending_mask&=~bit;delete_count++;return ESP_OK;
}
static void outbox_set_pending(void *o,int id,int status){(void)o;(void)id;(void)status;assert(0);}
static int esp_mqtt_dispatch_event(esp_mqtt_client_handle_t c){
    assert(c->event.event_id==MQTT_EVENT_SUBSCRIBED);
    event_count++;last_event_id=c->event.msg_id;return ESP_OK;
}
static int deliver_publish(esp_mqtt_client_handle_t c){(void)c;assert(0);return ESP_FAIL;}
static mqtt_message_t unused_message={1};
static mqtt_message_t *mqtt_msg_puback(void *c,int id){(void)c;(void)id;assert(0);return &unused_message;}
static mqtt_message_t *mqtt_msg_pubrec(void *c,int id){return mqtt_msg_puback(c,id);}
static mqtt_message_t *mqtt_msg_pubrel(void *c,int id){return mqtt_msg_puback(c,id);}
static mqtt_message_t *mqtt_msg_pubcomp(void *c,int id){return mqtt_msg_puback(c,id);}
static int mqtt_write_data(esp_mqtt_client_handle_t c){(void)c;assert(0);return ESP_FAIL;}
"""
suback_helpers = between(helpers, 'enum mqtt_message_type {', 'typedef struct mqtt_message {')
for name in ('mqtt_get_type', 'mqtt_get_qos', 'mqtt_get_dup'):
    suback_helpers += re.search(r'static inline int ' + name + r'\(.*?\n\}', helpers, re.S).group(0) + '\n'
suback_helpers += between(parser, 'uint32_t mqtt_get_total_length(', 'bool mqtt_header_complete(')
suback_helpers += between(parser, 'uint16_t mqtt_get_id(', 'mqtt_message_t *mqtt_msg_connect(')
suback_helpers += parser[parser.index('int mqtt_has_valid_msg_hdr('):]
suback_helpers += between(source, 'static esp_err_t esp_mqtt_dispatch_event_with_msgid(', 'static esp_err_t esp_mqtt_dispatch_event(')
suback_validator = between(source, 'static bool is_valid_mqtt_msg(', 'static void mqtt_enqueue_oversized(')
suback_receiver = between(source, 'static int mqtt_message_receive(', 'static esp_err_t mqtt_resend_queued(')
suback_suffix = r"""
static struct client c;
static uint8_t buffer[32];
static void setup(const uint8_t *data,size_t length){
    assert(length<=sizeof(wire));memcpy(wire,data,length);wire_length=length;wire_position=0;
    read_chunk=sizeof(wire);eof_error=false;event_count=delete_count=error_count=0;pending_mask=1;last_event_id=0;
    memset(&c,0,sizeof(c));memset(buffer,0xA5,sizeof(buffer));
    c.mqtt_state.in_buffer=buffer;c.mqtt_state.in_buffer_length=sizeof(buffer);
    c.mqtt_state.pending_msg_count=1;c.mqtt_state.pending_msg_id=17;
}
static void rejected(const uint8_t *data,size_t length){
    setup(data,length);
    assert(mqtt_process_receive(&c)==ESP_FAIL);
    assert(event_count==0&&delete_count==0&&pending_mask==1&&c.mqtt_state.pending_msg_count==1);
}
int main(void){
    uint8_t ack[]={0x90,3,0,17,1};
    for(unsigned grant=0;grant<=2;grant++){
        ack[4]=(uint8_t)grant;setup(ack,sizeof(ack));
        assert(mqtt_process_receive(&c)==ESP_OK);
        assert(event_count==1&&last_event_id==17&&delete_count==1&&pending_mask==0);
        assert(c.mqtt_state.pending_msg_count==0&&c.mqtt_state.in_buffer_read_len==0);
    }
    puts("PASS SUBACK accepts valid QoS 0, 1 and 2 grants and consumes matching request once");
    ack[4]=0x80;rejected(ack,sizeof(ack));
    ack[4]=3;rejected(ack,sizeof(ack));
    ack[4]=0xFF;rejected(ack,sizeof(ack));
    const uint8_t absent[]={0x90,2,0,17};rejected(absent,sizeof(absent));
    const uint8_t no_id[]={0x90,3,0,0,1};rejected(no_id,sizeof(no_id));
    const uint8_t extra[]={0x90,4,0,17,1,1};rejected(extra,sizeof(extra));
    const uint8_t flags[]={0x91,3,0,17,1};rejected(flags,sizeof(flags));
    const uint8_t short_id[]={0x90,1,0};rejected(short_id,sizeof(short_id));
    const uint8_t empty[]={0x90,0};rejected(empty,sizeof(empty));
    puts("PASS denied, reserved, missing-grant, zero-ID, extra-grant and malformed SUBACK never report success");
    ack[4]=1;
    for(size_t split=1;split<sizeof(ack);split++){
        setup(ack,sizeof(ack));wire_length=split;
        assert(mqtt_process_receive(&c)==ESP_OK);
        assert(event_count==0&&delete_count==0&&pending_mask==1);
        wire_length=sizeof(ack);
        assert(mqtt_process_receive(&c)==ESP_OK);
        assert(event_count==1&&delete_count==1&&pending_mask==0);
    }
    setup(ack,sizeof(ack));read_chunk=1;
    for(unsigned i=0;i<5&&event_count==0;i++)assert(mqtt_process_receive(&c)==ESP_OK);
    assert(event_count==1&&delete_count==1&&wire_position==sizeof(ack));
    puts("PASS valid SUBACK tolerates every split point and one-byte transport reads");
    setup(ack,sizeof(ack));wire_length=4;
    assert(mqtt_process_receive(&c)==ESP_OK&&event_count==0&&delete_count==0);
    eof_error=true;
    assert(mqtt_process_receive(&c)==ESP_FAIL&&event_count==0&&delete_count==0&&pending_mask==1);
    assert(error_count==1);
    puts("PASS truncated SUBACK waits for completion; transport failure never acknowledges it");
    const uint8_t wrong_id[]={0x90,3,0,31,1};setup(wrong_id,sizeof(wrong_id));
    assert(mqtt_process_receive(&c)==ESP_OK&&event_count==0&&delete_count==0&&pending_mask==1);
    uint8_t pair[]={0x90,3,0,17,1,0x90,3,0,29,1};setup(pair,sizeof(pair));
    pending_mask=3;c.mqtt_state.pending_msg_count=2;
    assert(mqtt_process_receive(&c)==ESP_OK&&event_count==1&&wire_position==5&&pending_mask==2);
    assert(mqtt_process_receive(&c)==ESP_OK&&event_count==2&&wire_position==10&&pending_mask==0);
    setup(ack,sizeof(ack));assert(mqtt_process_receive(&c)==ESP_OK);
    wire_position=0;
    assert(mqtt_process_receive(&c)==ESP_OK&&event_count==1&&delete_count==1);
    pair[9]=0x80;setup(pair,sizeof(pair));pending_mask=3;c.mqtt_state.pending_msg_count=2;
    assert(mqtt_process_receive(&c)==ESP_OK&&event_count==1&&pending_mask==2);
    assert(mqtt_process_receive(&c)==ESP_FAIL&&event_count==1&&pending_mask==2&&delete_count==1);
    puts("PASS unknown/duplicate IDs and adjacent ACKs cannot fabricate a second successful subscription");
    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='mqtt-suback-') as directory:
    path = Path(directory)
    def compile_receiver(receiver, name):
        test = path / (name + '.c')
        test.write_text(suback_prefix + suback_helpers + suback_validator + receiver + suback_suffix)
        exe = path / name
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare', '-fmax-errors=5',
                        '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
                        str(test), '-o', str(exe)], check=True)
        return exe
    subprocess.run([str(compile_receiver(suback_receiver, 'suback'))], check=True, timeout=15)
    # A regression must fail on the unpatched pinned implementation, not just pass
    # after the fix. The original emits success for 0x80 and hits rejected().
    original = subprocess.check_output(['git', '-C', str(mqtt), 'show', 'HEAD:mqtt_client.c'], text=True)
    old_receiver = between(original, 'static int mqtt_message_receive(', 'static esp_err_t mqtt_resend_queued(')
    result = subprocess.run([str(compile_receiver(old_receiver, 'suback-original'))], capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and 'rejected:' in result.stderr and 'Assertion' in result.stderr, result.stderr
    print('PASS regression rejects the original pinned SDK false-success behavior')
