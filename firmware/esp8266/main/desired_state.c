#include "desired_state.h"
#include <string.h>

bool desired_uuid_valid(const char *id) {
    if (!id || strlen(id)!=36) return false;
    for (unsigned i=0;i<36;i++) {
        if (i==8 || i==13 || i==18 || i==23) { if (id[i]!='-') return false; }
        else if (!((id[i]>='0'&&id[i]<='9') || (id[i]>='a'&&id[i]<='f'))) return false;
    }
    return true;
}
static uint32_t crc(const uint8_t *p,size_t n) {
    uint32_t c=UINT32_MAX;
    while (n--) { c^=*p++; for (unsigned i=0;i<8;i++) c=(c>>1)^((0u-(c&1u))&UINT32_C(0xedb88320)); }
    return ~c;
}
static void put(uint8_t *p,uint64_t v,unsigned n) { for(unsigned i=0;i<n;i++) p[i]=(uint8_t)(v>>(8*i)); }
static uint64_t get(const uint8_t *p,unsigned n) { uint64_t v=0; for(unsigned i=0;i<n;i++) v|=(uint64_t)p[i]<<(8*i); return v; }
static bool valid(const desired_value_t *v) {
    return v->revision>0 && v->revision<=DESIRED_MAX_REVISION && v->expires_epoch>0 && v->speed<=100 && desired_uuid_valid(v->command_id);
}
static void encode(const desired_value_t *v,uint8_t p[DESIRED_RECORD_SIZE]) {
    memset(p,0,DESIRED_RECORD_SIZE); memcpy(p,"ADS1",4);
    put(p+4,v->revision,8); put(p+12,(uint64_t)v->expires_epoch,8);
    p[20]=v->power; p[21]=v->speed; memcpy(p+22,v->command_id,37);
    put(p+60,crc(p,60),4);
}
bool desired_open(desired_store_t *s,void *ctx,int (*read)(void *,uint8_t *,size_t *),int (*write)(void *,const uint8_t *,size_t)) {
    memset(s,0,sizeof(*s)); s->context=ctx; s->write=write;
    uint8_t p[DESIRED_RECORD_SIZE]; size_t n=sizeof(p); int result=read(ctx,p,&n);
    if (result==1) return true;
    if (result || n!=sizeof(p) || memcmp(p,"ADS1",4) || p[20]>1 || p[58] || p[59] || get(p+60,4)!=crc(p,60)) goto fault;
    s->value.revision=get(p+4,8); s->value.expires_epoch=(int64_t)get(p+12,8);
    s->value.power=p[20]!=0; s->value.speed=p[21]; memcpy(s->value.command_id,p+22,37);
    if (valid(&s->value)) return true;
fault:
    s->faulted=true; return false;
}
desired_result_t desired_accept(desired_store_t *s,const desired_value_t *next,int64_t now) {
    if(s->faulted) return DESIRED_IO;
    if(now<INT64_C(1700000000) || !valid(next) || next->expires_epoch<=now || next->revision<s->value.revision) return DESIRED_REJECTED;
    if(next->revision==s->value.revision) {
        return next->power==s->value.power && next->speed==s->value.speed && next->expires_epoch==s->value.expires_epoch && !strcmp(next->command_id,s->value.command_id) ? DESIRED_ACCEPTED : DESIRED_REJECTED;
    }
    uint8_t record[DESIRED_RECORD_SIZE]; encode(next,record);
    if(s->write(s->context,record,sizeof(record))) {s->faulted=true; return DESIRED_IO;}
    s->value=*next; return DESIRED_ACCEPTED;
}
bool desired_restorable(const desired_store_t *s,int64_t now) {
    return !s->faulted && now>=INT64_C(1700000000) && valid(&s->value) && s->value.expires_epoch>now;
}
