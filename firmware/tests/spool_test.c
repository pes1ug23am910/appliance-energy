#include "telemetry_spool.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    uint8_t records[SPOOL_CAPACITY][SPOOL_RECORD_MAX];
    size_t sizes[SPOOL_CAPACITY];
    int write_fault; /* 1: before commit, 2: after commit before return. */
    int erase_fault;
} disk_t;
static disk_t disk;
static int read_record(void *context,unsigned slot,uint8_t *value,size_t *size) {
    disk_t *d=context;
    if (!d->sizes[slot]) return 1;
    if (*size<d->sizes[slot]) return -1;
    *size=d->sizes[slot]; memcpy(value,d->records[slot],*size); return 0;
}
static int write_record(void *context,unsigned slot,const uint8_t *value,size_t size) {
    disk_t *d=context;
    if (d->write_fault==1) return -1;
    memcpy(d->records[slot],value,size); d->sizes[slot]=size;
    return d->write_fault==2 ? -1 : 0;
}
static int erase_record(void *context,unsigned slot) {
    disk_t *d=context;
    if (d->erase_fault==1) return -1;
    d->sizes[slot]=0; return d->erase_fault==2 ? -1 : 0;
}
static spool_storage_t storage(void) {
    return (spool_storage_t){&disk,read_record,write_record,erase_record};
}
static const char *id="00000000-0000-4000-8000-000000000001";
static const char *other="00000000-0000-4000-8000-000000000002";
static const char *payload="{\"event_id\":\"00000000-0000-4000-8000-000000000001\",\"power_w\":42}";
static void reset(telemetry_spool_t *s) { memset(&disk,0,sizeof(disk)); assert(spool_open(s,storage())==SPOOL_OK); }

int main(void) {
    telemetry_spool_t s,reboot; char value[SPOOL_PAYLOAD_MAX];
    reset(&s);
    assert(spool_append(&s,id,payload)==SPOOL_OK);
    assert(spool_open(&reboot,storage())==SPOOL_OK);
    assert(spool_count(&reboot)==1);
    assert(spool_read(&reboot,0,value,sizeof(value))==SPOOL_OK && !strcmp(payload,value));
    assert(spool_append(&reboot,id,payload)==SPOOL_OK && spool_count(&reboot)==1);
    assert(spool_append(&reboot,id,"changed")==SPOOL_INVALID);
    puts("PASS immutable payload survives reboot and retry");

    for (int fault=1; fault<=2; fault++) {
        reset(&s); disk.write_fault=fault;
        assert(spool_append(&s,id,payload)==SPOOL_IO);
        assert(spool_append(&s,other,"new")==SPOOL_IO);
        assert(spool_read(&s,0,value,sizeof(value))==SPOOL_IO);
        disk.write_fault=0;
        assert(spool_open(&reboot,storage())==SPOOL_OK);
        assert(spool_count(&reboot)==(unsigned)(fault==2));
        if (fault==2) assert(spool_read(&reboot,0,value,sizeof(value))==SPOOL_OK && !strcmp(value,payload));
    }
    puts("PASS cuts before/after append commit cannot overwrite ambiguous records");

    for (int fault=1; fault<=2; fault++) {
        reset(&s); assert(spool_append(&s,id,payload)==SPOOL_OK); disk.erase_fault=fault;
        assert(spool_accept(&s,id)==SPOOL_IO);
        assert(spool_append(&s,other,"new")==SPOOL_IO);
        disk.erase_fault=0;
        assert(spool_open(&reboot,storage())==SPOOL_OK);
        assert(spool_count(&reboot)==(unsigned)(fault==1));
        if (fault==1) assert(spool_read(&reboot,0,value,sizeof(value))==SPOOL_OK && !strcmp(value,payload));
    }
    puts("PASS cuts before/after receipt commit replay safely or preserve accepted deletion");

    reset(&s); assert(spool_append(&s,id,payload)==SPOOL_OK);
    assert(spool_accept(&s,other)==SPOOL_ABSENT && spool_count(&s)==1);
    assert(spool_accept(&s,"bad-id")==SPOOL_INVALID && spool_count(&s)==1);
    assert(spool_accept(&s,id)==SPOOL_OK);
    assert(spool_accept(&s,id)==SPOOL_ABSENT);
    assert(spool_open(&reboot,storage())==SPOOL_OK && spool_count(&reboot)==0);
    puts("PASS only matching receipt retires a record and repeated receipts are harmless");

    reset(&s); assert(spool_append(&s,id,payload)==SPOOL_OK);
    const char *large_sequence="{\"boot_id\":\"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb\",\"sequence\":4294967295,\"energy_wh_total\":123.5}";
    assert(spool_append(&s,other,large_sequence)==SPOOL_OK);
    assert(spool_accept(&s,other)==SPOOL_OK && spool_count(&s)==1);
    assert(spool_accept(&s,other)==SPOOL_ABSENT && spool_count(&s)==1);
    assert(spool_open(&reboot,storage())==SPOOL_OK);
    assert(spool_read(&reboot,0,value,sizeof(value))==SPOOL_OK && !strcmp(value,payload));
    assert(spool_append(&reboot,other,large_sequence)==SPOOL_OK);
    assert(spool_open(&s,storage())==SPOOL_OK);
    assert(spool_read(&s,1,value,sizeof(value))==SPOOL_OK && !strcmp(value,large_sequence));
    puts("PASS reordered receipts preserve other events and old-boot 32-bit sequence payloads");

    reset(&s);
    for (unsigned i=0;i<SPOOL_CAPACITY;i++) {
        char generated[37]; snprintf(generated,sizeof(generated),"00000000-0000-4000-8000-%012u",i+10);
        assert(spool_append(&s,generated,payload)==SPOOL_OK);
    }
    assert(spool_append(&s,id,"overflow")==SPOOL_FULL);
    assert(spool_open(&reboot,storage())==SPOOL_OK && spool_count(&reboot)==SPOOL_CAPACITY);
    for (unsigned i=0;i<SPOOL_CAPACITY;i++) assert(spool_read(&reboot,i,value,sizeof(value))==SPOOL_OK && !strcmp(value,payload));
    puts("PASS bounded spool never evicts unacknowledged data on overflow");

    reset(&s); memset(value,'x',sizeof(value)); value[sizeof(value)-1]=0;
    assert(spool_append(&s,id,value)==SPOOL_OK);
    assert(spool_open(&reboot,storage())==SPOOL_OK);
    char restored[SPOOL_PAYLOAD_MAX]; assert(spool_read(&reboot,0,restored,sizeof(restored))==SPOOL_OK);
    assert(!strcmp(value,restored));
    assert(spool_read(&reboot,0,restored,2)==SPOOL_INVALID);
    char too_big[SPOOL_PAYLOAD_MAX+1]; memset(too_big,'x',sizeof(too_big)-1); too_big[sizeof(too_big)-1]=0;
    assert(spool_append(&s,other,too_big)==SPOOL_INVALID);
    puts("PASS exact payload boundary and insufficient read buffer are checked");

    reset(&s); assert(spool_append(&s,id,payload)==SPOOL_OK);
    disk.records[0][55]^=1;
    assert(spool_open(&reboot,storage())==SPOOL_IO && reboot.faulted);
    assert(spool_accept(&reboot,id)==SPOOL_IO);
    reset(&s); assert(spool_append(&s,id,payload)==SPOOL_OK);
    disk.sizes[0]--;
    assert(spool_open(&reboot,storage())==SPOOL_IO);
    reset(&s); assert(spool_append(&s,id,payload)==SPOOL_OK);
    disk.records[0][0]^=1;
    assert(spool_open(&reboot,storage())==SPOOL_IO);
    puts("PASS corrupt, truncated and unknown-version records fail closed");

    reset(&s); assert(spool_append(&s,id,payload)==SPOOL_OK);
    memcpy(disk.records[1],disk.records[0],disk.sizes[0]); disk.sizes[1]=disk.sizes[0];
    assert(spool_open(&reboot,storage())==SPOOL_IO);
    puts("PASS duplicate persisted identities fail closed");
    puts("9 spool fault suites passed (host storage model, not physical flash)");
    return 0;
}
