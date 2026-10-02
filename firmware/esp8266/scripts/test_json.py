"""Exercise actual ESP8266 JSON helpers with pinned cJSON and allocation faults."""
from pathlib import Path
import os, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
sdk=Path(os.environ.get('IDF_PATH','/opt/esp8266'))
cjson=sdk/'components/json/cJSON'
source=(root/'main/main.c').read_text()
start=source.index('static cJSON *json_object(')
end=source.index('static bool publish_json(',start)
helpers=source[start:end]
header=r'''
#include <assert.h>
#include <setjmp.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "cJSON.h"
#include "desired_state.h"
#define ESP_LOGI(...) ((void)0)
typedef unsigned char StackType_t;
static unsigned esp_get_free_heap_size(void){return 12345;}
static unsigned uxTaskGetStackHighWaterMark(void *task){(void)task;return 4096;}
static jmp_buf recovery;
static const char *failure;
static size_t allocation_count,fail_at,outstanding;
static bool format_error;
static void *checked_alloc(size_t n){
    allocation_count++;
    if(fail_at&&allocation_count==fail_at)return NULL;
    void *p=malloc(n);if(p)outstanding++;return p;
}
static void checked_free(void *p){if(p){assert(outstanding);outstanding--;free(p);}}
static void fail_closed(const char *reason){failure=reason;longjmp(recovery,1);}
int __wrap_sprintf(char *out,const char *format,...){
    if(format_error&&strchr(format,'g'))return -1;
    va_list args;va_start(args,format);int count=vsprintf(out,format,args);va_end(args);return count;
}
'''
# The firmware owns PrintUnformatted's returned text via ordinary free(). Its
# hooks here use the same allocator plus accounting, so track this ownership too.
helpers=helpers.replace('free(text);','checked_free(text);')
footer=r'''
static void reset(size_t index){assert(outstanding==0);allocation_count=0;fail_at=index;failure=NULL;}
static void flags(void){
    cJSON *body=json_object();cJSON *array=cJSON_AddArrayToObject(body,"quality_flags");json_member(body,array);
    json_flag(body,array,"setpoint_model_no_energy_sensor");json_flag(body,array,"gpio_output_disabled");
    char *text=serialize_json(body);assert(strstr(text,"gpio_output_disabled"));checked_free(text);
}
int main(void){
    cJSON_Hooks hooks={checked_alloc,checked_free};cJSON_InitHooks(&hooks);
    reset(0);if(setjmp(recovery)==0)json_numeric_self_test();else assert(0);
    size_t numeric_allocations=allocation_count;assert(outstanding==0&&numeric_allocations>10);
    puts("PASS actual helper numeric roundtrip: integer, fractional energy and maximum JSON-safe revision");
    for(size_t i=1;i<=numeric_allocations;i++){
        reset(i);if(setjmp(recovery)==0){json_numeric_self_test();assert(0);}
        else {assert(failure&&strstr(failure,"JSON"));assert(outstanding==0);}
    }
    puts("PASS every numeric object/member/serialization/parse allocation failure is fail-closed without leaks");
    reset(0);if(setjmp(recovery)==0)flags();else assert(0);
    size_t flag_allocations=allocation_count;assert(outstanding==0);
    for(size_t i=1;i<=flag_allocations;i++){
        reset(i);if(setjmp(recovery)==0){flags();assert(0);}
        else {assert(failure&&strstr(failure,"JSON"));assert(outstanding==0);}
    }
    puts("PASS quality-flag allocation failures cannot emit a partial document or leak memory");
    reset(0);format_error=true;
    if(setjmp(recovery)==0){json_numeric_self_test();assert(0);}
    else {assert(strcmp(failure,"JSON serialization failed")==0);assert(outstanding==0);}
    puts("PASS numeric formatter failure is identified as serialization failure before publication");
    format_error=false;reset(0);json_numeric_self_test();assert(outstanding==0);
    printf("PASS allocator fault positions: numeric=%u quality_flags=%u\n",(unsigned)numeric_allocations,(unsigned)flag_allocations);
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='appliance-json-') as directory:
    p=Path(directory);test=p/'test.c';test.write_text(header+helpers+footer)
    command=['cc','-std=c11','-Wall','-Wextra','-Wno-unused-function','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie','-I'+str(cjson),'-I'+str(root/'main'),str(test),str(cjson/'cJSON.c'),'-Wl,--wrap=sprintf','-lm','-o',str(p/'test')]
    subprocess.run(command,check=True,timeout=45)
    subprocess.run([str(p/'test')],check=True,timeout=15)
