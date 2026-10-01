#include "telemetry_spool.h"
#include <string.h>

static uint32_t crc32(const uint8_t *data, size_t length) {
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < length; i++) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}
static void put32(uint8_t *p, uint32_t value) {
    for (unsigned i = 0; i < 4; i++) p[i] = (uint8_t)(value >> (8 * i));
}
static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static bool valid_id(const char *id) {
    if (!id || strlen(id) != 36) return false;
    for (unsigned i = 0; i < 36; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) { if (id[i] != '-') return false; }
        else if (!((id[i] >= '0' && id[i] <= '9') || (id[i] >= 'a' && id[i] <= 'f'))) return false;
    }
    return true;
}
static bool decode(const uint8_t *record, size_t size) {
    if (size < 50 || size > SPOOL_RECORD_MAX || get32(record) != 0x31505341u) return false;
    if (get32(record + 4) != size || record[48] || record[size - 1]) return false;
    if (!valid_id((const char *)(record + 12))) return false;
    return get32(record + 8) == crc32(record + 12, size - 12) &&
           strlen((const char *)(record + 49)) == size - 50;
}
static spool_result_t fail(telemetry_spool_t *spool) { spool->faulted = true; return SPOOL_IO; }
spool_result_t spool_open(telemetry_spool_t *spool, spool_storage_t storage) {
    memset(spool, 0, sizeof(*spool));
    spool->storage = storage;
    if (!storage.read || !storage.write || !storage.erase) return fail(spool);
    for (unsigned i = 0; i < SPOOL_CAPACITY; i++) {
        uint8_t record[SPOOL_RECORD_MAX]; size_t size = sizeof(record);
        int result = storage.read(storage.context, i, record, &size);
        if (result == 1) continue;
        if (result != 0 || !decode(record, size)) return fail(spool);
        for (unsigned j = 0; j < i; j++) if (!strcmp(spool->ids[j], (const char *)(record + 12))) return fail(spool);
        memcpy(spool->ids[i], record + 12, 37);
    }
    return SPOOL_OK;
}
spool_result_t spool_read(telemetry_spool_t *spool, unsigned slot, char *payload, size_t capacity) {
    if (spool->faulted) return SPOOL_IO;
    if (slot >= SPOOL_CAPACITY || !payload) return SPOOL_INVALID;
    if (!spool->ids[slot][0]) return SPOOL_ABSENT;
    uint8_t record[SPOOL_RECORD_MAX]; size_t size = sizeof(record);
    if (spool->storage.read(spool->storage.context, slot, record, &size) || !decode(record, size) ||
        strcmp(spool->ids[slot], (const char *)(record + 12))) return fail(spool);
    if (capacity < size - 49) return SPOOL_INVALID;
    memcpy(payload, record + 49, size - 49);
    return SPOOL_OK;
}
spool_result_t spool_append(telemetry_spool_t *spool, const char *id, const char *payload) {
    if (spool->faulted) return SPOOL_IO;
    if (!valid_id(id) || !payload || !payload[0] || strlen(payload) >= SPOOL_PAYLOAD_MAX) return SPOOL_INVALID;
    for (unsigned i = 0; i < SPOOL_CAPACITY; i++) if (!strcmp(spool->ids[i], id)) {
        char existing[SPOOL_PAYLOAD_MAX];
        spool_result_t result = spool_read(spool, i, existing, sizeof(existing));
        if (result != SPOOL_OK) return result;
        return strcmp(existing, payload) ? SPOOL_INVALID : SPOOL_OK;
    }
    unsigned slot;
    for (slot = 0; slot < SPOOL_CAPACITY && spool->ids[slot][0]; slot++) {}
    if (slot == SPOOL_CAPACITY) return SPOOL_FULL;
    uint8_t record[SPOOL_RECORD_MAX] = {0}; size_t size = 50 + strlen(payload);
    put32(record, 0x31505341u); put32(record + 4, (uint32_t)size);
    memcpy(record + 12, id, 37); memcpy(record + 49, payload, size - 49);
    put32(record + 8, crc32(record + 12, size - 12));
    if (spool->storage.write(spool->storage.context, slot, record, size)) return fail(spool);
    memcpy(spool->ids[slot], id, 37);
    return SPOOL_OK;
}
spool_result_t spool_accept(telemetry_spool_t *spool, const char *id) {
    if (spool->faulted) return SPOOL_IO;
    if (!valid_id(id)) return SPOOL_INVALID;
    for (unsigned i = 0; i < SPOOL_CAPACITY; i++) if (!strcmp(spool->ids[i], id)) {
        if (spool->storage.erase(spool->storage.context, i)) return fail(spool);
        spool->ids[i][0] = 0;
        return SPOOL_OK;
    }
    return SPOOL_ABSENT;
}
unsigned spool_count(const telemetry_spool_t *spool) {
    unsigned count = 0;
    for (unsigned i = 0; i < SPOOL_CAPACITY; i++) count += spool->ids[i][0] != 0;
    return count;
}
