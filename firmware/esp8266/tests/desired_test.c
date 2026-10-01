#include "desired_state.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef struct { uint8_t data[DESIRED_RECORD_SIZE]; size_t size; int cut; unsigned writes; bool exists; } memory_t;
static int read_record(void *ctx,uint8_t *p,size_t *n) {memory_t *m=ctx;if(!m->exists)return 1;if(*n<m->size)return -1;memcpy(p,m->data,m->size);*n=m->size;return 0;}
static int write_record(void *ctx,const uint8_t *p,size_t n) {memory_t *m=ctx;m->writes++;if(m->cut==1)return -1;memcpy(m->data,p,n);m->size=n;m->exists=true;return m->cut==2?-1:0;}
static desired_value_t value(uint64_t revision) {desired_value_t v={.revision=revision,.expires_epoch=INT64_C(1800000060),.power=true,.speed=80};strcpy(v.command_id,"01234567-89ab-4cde-8fab-0123456789ab");return v;}
int main(void) {
    const int64_t now=INT64_C(1800000000);
    memory_t m={0};desired_store_t s;assert(desired_open(&s,&m,read_record,write_record));
    assert(!desired_restorable(&s,now)); desired_value_t v=value(UINT64_C(4294967297));
    assert(desired_accept(&s,&v,now)==DESIRED_ACCEPTED);assert(m.writes==1);
    assert(desired_accept(&s,&v,now)==DESIRED_ACCEPTED);assert(m.writes==1);
    v.speed=79;assert(desired_accept(&s,&v,now)==DESIRED_REJECTED);v.speed=80;
    v.revision--;assert(desired_accept(&s,&v,now)==DESIRED_REJECTED);v.revision++;
    assert(desired_open(&s,&m,read_record,write_record));assert(s.value.revision==UINT64_C(4294967297));
    assert(desired_restorable(&s,now));assert(!desired_restorable(&s,0));assert(!desired_restorable(&s,now+60));
    assert(desired_accept(&s,&v,now+60)==DESIRED_REJECTED);
    puts("PASS revision above 32 bits, exact duplicate, stale/conflict fencing and expiry");
    for(int cut=1;cut<=2;cut++) {
        memory_t disk=m;disk.cut=cut;assert(desired_open(&s,&disk,read_record,write_record));v=value(UINT64_C(4294967298));
        assert(desired_accept(&s,&v,now)==DESIRED_IO);assert(!desired_restorable(&s,now));
        v.revision++;assert(desired_accept(&s,&v,now)==DESIRED_IO);assert(disk.writes==2);
        disk.cut=0;assert(desired_open(&s,&disk,read_record,write_record));
        assert(s.value.revision==(cut==1?UINT64_C(4294967297):UINT64_C(4294967298)));
    }
    puts("PASS commit interruption before/after persistence fails closed until reopen");
    for(size_t i=0;i<DESIRED_RECORD_SIZE;i++) {memory_t corrupt=m;corrupt.data[i]^=1;assert(!desired_open(&s,&corrupt,read_record,write_record));assert(!desired_restorable(&s,now));}
    memory_t truncated=m;truncated.size--;assert(!desired_open(&s,&truncated,read_record,write_record));
    puts("PASS every persisted byte corruption and truncation rejected");
    assert(desired_open(&s,&m,read_record,write_record));v=value(DESIRED_MAX_REVISION);assert(desired_accept(&s,&v,now)==DESIRED_ACCEPTED);
    assert(desired_open(&s,&m,read_record,write_record));assert(s.value.revision==DESIRED_MAX_REVISION);
    v.revision++;assert(desired_accept(&s,&v,now)==DESIRED_REJECTED);v=value(1);strcpy(v.command_id,"zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz");assert(desired_accept(&s,&v,now)==DESIRED_REJECTED);
    puts("PASS JSON-safe 64-bit maximum round trip and malformed UUID rejected");
    return 0;
}
