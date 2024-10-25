#include <dragon/utils.h>
#include "_utils.h"
#include <dragon/return_codes_map.h>
#include "hostid.h"
#include "err.h"
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/types.h>
#include <stdatomic.h>
#include <ctype.h>
#include <math.h>
#include <fcntl.h>
#include <unistd.h>

#define ONE_BILLION 1000000000
#define ONE_MILLION 1000000
#define NSEC_PER_SECOND 1000000000

bool dg_enable_errstr = true;
_Thread_local char * errstr = NULL;
static _Thread_local bool dg_thread_local_mode = false;

const char*
dragon_get_rc_string(const dragonError_t rc)
{
    if (rc > dragon_max_rc_value)
        return dragon_rc_map[dragon_max_rc_value];

    return dragon_rc_map[rc];
}


void
_set_errstr(char * new_errstr)
{
    if (errstr != NULL)
        free(errstr);

    if (new_errstr == NULL)
        errstr = NULL;
    else
        errstr = strndup(new_errstr, DRAGON_MAX_ERRSTR_REC_LEN+1);
}


void
_append_errstr(char * more_errstr)
{
    if (errstr == NULL) {
        _set_errstr(more_errstr);
    } else {
        char * new_errstr = malloc(sizeof(char) * (strlen(errstr) +
                                        strnlen(more_errstr, DRAGON_MAX_ERRSTR_REC_LEN) + 1));
        if (new_errstr != NULL) {
            strcpy(new_errstr, errstr);
            strncat(new_errstr, more_errstr, DRAGON_MAX_ERRSTR_REC_LEN+1);
            free(errstr);
            errstr = new_errstr;
        }
    }
}


char *
_errstr_with_code(char * str, int code)
{
    char * new_str = malloc(sizeof(char) * (strnlen(str, DRAGON_MAX_ERRSTR_REC_LEN) +
                                            snprintf(NULL, 0, " %s", dragon_get_rc_string(code)) + 1));
    sprintf(new_str, "%s %s", str, dragon_get_rc_string(code));
    return new_str;
}


char *
dragon_getlasterrstr()
{
    char * str;
    if (errstr == NULL) {
        str = strdup("");
    } else {
        char* message = "Traceback (most recent call first):\n";
        str = malloc(sizeof(char) * (strlen(errstr) + strlen(message) + 1));
        if (str != NULL) {
            strcpy(str, message);
            strcat(str, errstr);
        } else
            str = strdup(errstr);
    }
    return str;
}

void
dragon_enable_errstr(bool enable_errstr)
{
    dg_enable_errstr = enable_errstr;
}

dragonError_t
_lower_id(char *boot_id)
{
    while (*boot_id != '\0') {
        *boot_id = tolower(*boot_id);
        boot_id++;
    }
    no_err_return(DRAGON_SUCCESS);
}


dragonError_t
_sanitize_id(char *boot_id)
{
    // make everything lower
    if (_lower_id(boot_id) != DRAGON_SUCCESS)
        err_return(DRAGON_FAILURE, "Unable to lower boot ID hex");

    // Remove all non-hex characters
    char *pr = boot_id;
    char *pw = boot_id;
    while (*pr) {
        *pw = *pr++;
        if (isxdigit(*pw)) pw++;
    }
    *pw = '\0';

    no_err_return(DRAGON_SUCCESS);
}

int
_get_dec_from_hex(char hex) {

    /* This only works for lowercase hex letters and digits. Don't use
       for anything else! */

    if (isdigit(hex))
        return hex - '0';
    else
        return hex - 'a';
}

dragonError_t
_hex_to_dec(char *hex, uint64_t *dec)
{
    *dec = 0UL;
    int i, len = strlen(hex);
    int start = len - 16;

    if (start < 0)
        err_return(DRAGON_INVALID_ARGUMENT, "Hex string less than 8 bytes");

    // Read the last 16 digits and convert
    for (i = start;  i < len; i++) {
        *dec += *dec * 16 + _get_dec_from_hex(hex[i]);
    }

    no_err_return(DRAGON_SUCCESS);
}


dragonError_t
_get_hostid_from_bootid(uint64_t *host_id)
{
    int fd;
    size_t n, bsize = 512;
    char boot_id[bsize];
    char *filename = "/proc/sys/kernel/random/boot_id";

    // Read hex boot id
    if ((fd = open(filename, O_RDONLY|O_CLOEXEC|O_NOCTTY)) == -1)
        err_return(DRAGON_FAILURE, "Unable to open /proc/sys/kernel/random/boot_id for host ID generation");

    if ((n = read(fd, boot_id, bsize)) == -1)
        err_return(DRAGON_FAILURE, "Unable to read /proc/sys/kernel/random/boot_id for host ID generation");

    boot_id[n] = '\0';
    close(fd);

    // Clean out any non-hex charactars and convert to dec
    if (_sanitize_id(boot_id) != DRAGON_SUCCESS)
        err_return(DRAGON_FAILURE, "Unable to sanitize boot ID");

    if (_hex_to_dec(boot_id, host_id) != DRAGON_SUCCESS)
        err_return(DRAGON_FAILURE, "Unable to convert boot ID from hex to dec");

    no_err_return(DRAGON_SUCCESS);
}

dragonULInt dg_hostid;
dragonUInt dg_pid;
atomic_uint dg_ctr;
int dg_hostid_called = 0;

dragonULInt
dragon_host_id()
{
    if (dg_hostid_called == 0) {

        uint64_t lg_hostid;
        if (_get_hostid_from_bootid(&lg_hostid) != DRAGON_SUCCESS)
            err_return(DRAGON_FAILURE, "Unable to generate host ID from boot ID");
        pid_t pid = getpid();
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);

        dg_ctr = (uint32_t)(1.0e-9 * (ONE_BILLION * now.tv_sec + now.tv_nsec));
        dg_hostid = (dragonULInt)lg_hostid;
        dg_pid = (dragonUInt)pid;

        dg_hostid_called = 1;
    }

    return dg_hostid;
}

dragonError_t
dragon_set_host_id(dragonULInt id)
{
    if (dg_hostid_called == 1) {
        err_return(DRAGON_INVALID_ARGUMENT, "Cannot set host ID after it has been previously set");
    }
    else {
        pid_t pid = getpid();
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);

        dg_ctr = (uint32_t)(1.0e-9 * (ONE_BILLION * now.tv_sec + now.tv_nsec));
        dg_hostid = id;
        dg_pid = (dragonUInt)pid;

        dg_hostid_called = 1;
    }
    no_err_return(DRAGON_SUCCESS);
}

/* get the front end's external IP address, along with the IP address
 * for the head node, which are used to identify this Dragon runtime */
dragonULInt
dragon_get_local_rt_uid()
{
    static dragonULInt rt_uid = 0UL;

    if (rt_uid == 0UL) {
        char *rt_uid_str = getenv("DRAGON_RT_UID");

        /* Return 0 to indicate failure */
        if (rt_uid_str == NULL)
            return 0UL;

        rt_uid = (dragonULInt) strtoul(rt_uid_str, NULL, 10);
    }

    return rt_uid;
}

dragonULInt
dragon_get_my_puid()
{
    static dragonULInt local_get_puid = 0UL;
    static bool get_puid_called = false;

    if (get_puid_called)
        return local_get_puid;

    get_puid_called = true;

    char* puid_str = getenv("DRAGON_MY_PUID");

    if (puid_str != NULL)
        local_get_puid = (dragonULInt) strtoul(puid_str, NULL, 10);

    return local_get_puid;
}

dragonULInt
dragon_get_env_var_as_ulint(char* env_key)
{
    dragonULInt ret_val = 0UL;

    if (env_key == NULL)
        return 0UL;

    char* env_val = getenv(env_key);

    if (env_val != NULL)
        ret_val = (dragonULInt) strtoul(env_val, NULL, 10);

    return ret_val;
}

dragonError_t
dragon_set_env_var_as_ulint(char* env_key, dragonULInt val)
{
    if (env_key == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "Cannot set NULL key");

    char env_val[200];
    snprintf(env_val, 199, "%lu", val);

    int rc = setenv(env_key, env_val, 1);

    if (rc != 0) {
        char err_str[200];
        snprintf(err_str, 199, "Error on setting env var with EC=%d", rc);
        err_return(DRAGON_INVALID_OPERATION, err_str);
    }

    no_err_return(DRAGON_SUCCESS);
}

dragonError_t
dragon_unset_env_var(char* env_key)
{
    if (env_key == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "Cannot unset NULL key");

    int rc = unsetenv(env_key);
    if (rc != 0) {
        char err_str[200];
        snprintf(err_str, 199, "Error on unsetting env var with EC=%d", rc);
        err_return(DRAGON_INVALID_OPERATION, err_str);
    }

    no_err_return(DRAGON_SUCCESS);
}

dragonError_t
dragon_set_procname(char * name)
{
    if (name == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "The name argument cannot be NULL.");
    prctl(PR_SET_NAME, (unsigned long)name, 0uL, 0uL, 0uL);
    no_err_return(DRAGON_SUCCESS);
}

void
dragon_zero_uuid(dragonUUID uuid)
{
    dragonULInt * zptr = (dragonULInt *)&uuid[0];
    *zptr = 0UL;

    zptr++;
    *zptr = 0UL;
}

void
dragon_generate_uuid(dragonUUID uuid)
{
    dragonULInt hid = dragon_host_id();
    uint32_t ctr = atomic_fetch_add(&dg_ctr, 1UL);
    uint32_t pid = (uint32_t)dg_pid;

    dragonULInt * huid_ptr = (dragonULInt *)&uuid[DRAGON_UUID_OFFSET_HID];
    *huid_ptr = hid;

    dragonUInt * pid_ptr = (dragonUInt *)&uuid[DRAGON_UUID_OFFSET_PID];
    *pid_ptr = pid;

    dragonUInt * ctr_ptr = (dragonUInt *)&uuid[DRAGON_UUID_OFFSET_CTR];
    *ctr_ptr = ctr;
}

int
dragon_compare_uuid(const dragonUUID u1, const dragonUUID u2)
{
    dragonULInt * u1_head = (dragonULInt *)&u1[0];
    dragonULInt * u1_tail = (dragonULInt *)&u1[8];

    dragonULInt * u2_head = (dragonULInt *)&u2[0];
    dragonULInt * u2_tail = (dragonULInt *)&u2[8];

    if (u1_head < u2_head)
        return -1;
    if (u1_head > u2_head)
        return 1;
    if (u1_head == u2_head) {
        if (u1_tail < u2_tail)
            return -1;
        if (u1_tail > u2_tail)
            return 1;
        if (u1_tail == u2_tail)
            return 0;
    }

    return 0;
}

dragonError_t
dragon_encode_uuid(const dragonUUID uuid, void * ptr)
{
    if (ptr == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "destination pointer is invalid");

    memcpy(ptr, (void *)uuid, sizeof(dragonUUID));
    no_err_return(DRAGON_SUCCESS);
}

dragonError_t
dragon_decode_uuid(const void * ptr, dragonUUID uuid)
{
    if (ptr == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "source pointer is invalid");

    memcpy((void *)uuid, ptr, sizeof(dragonUUID));
    no_err_return(DRAGON_SUCCESS);
}

dragonULInt
dragon_get_host_id_from_uuid(dragonUUID uuid)
{
    return *(dragonULInt *)&uuid[DRAGON_UUID_OFFSET_HID];
}

pid_t
dragon_get_pid_from_uuid(dragonUUID uuid)
{
    return *(pid_t *)&uuid[DRAGON_UUID_OFFSET_PID];
}

uint32_t
dragon_get_ctr_from_uuid(dragonUUID uuid)
{
    return *(uint32_t *)&uuid[DRAGON_UUID_OFFSET_CTR];
}

// The while loop below ensures the timespec result is normalized.
dragonError_t
dragon_timespec_add(timespec_t* result, const timespec_t* first, const timespec_t* second)
{
    if (result == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "The result argument must be non-NULL\n");

    if (first == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "The first argument must be non-NULL\n");

    if (second == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "The second argument must be non-NULL\n");

    result->tv_sec = first->tv_sec + second->tv_sec;
    result->tv_nsec = first->tv_nsec + second->tv_nsec;
    while (result->tv_nsec >= ONE_BILLION) {
        result->tv_sec += 1;
        result->tv_nsec -= ONE_BILLION;
    }

    no_err_return(DRAGON_SUCCESS);
}

// The while loop below ensures the timespec result is normalized.
dragonError_t
dragon_timespec_diff(timespec_t* result, const timespec_t* first, const timespec_t* second)
{
    if (result == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "The result argument must be non-NULL\n");

    if (first == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "The first argument must be non-NULL\n");

    if (second == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "The second argument must be non-NULL\n");

    result->tv_sec = first->tv_sec - second->tv_sec;
    result->tv_nsec = first->tv_nsec - second->tv_nsec;

    while (result->tv_nsec < 0) {
        result->tv_sec -= 1;
        result->tv_nsec += ONE_BILLION;
    }

    no_err_return(DRAGON_SUCCESS);
}

// This comparison assumes the two timespecs are normalized.
bool
dragon_timespec_le(const timespec_t* first, const timespec_t* second)
{
    return ((first->tv_sec < second->tv_sec) ||
            ((first->tv_sec == second->tv_sec) && (first->tv_nsec <= second->tv_nsec)));
}


/***************************************************************************************
 * Find the deadline for a given timespec timeout.
 *
 * This function initializes a deadline based on the current time and the value of timer.
 *
 * @param timer A pointer to a timespec structure or NULL. If not null, then it has
 * the timeout value to be used in the computation of the deadline.
 * @param deadline A pointer to a timespec structure that holds the time when the timer
 * has expired.
 * @returns DRAGON_SUCCESS or DRAGON_INVALID_ARGUMENT
 **********************************************************************************/

dragonError_t
dragon_timespec_deadline(const timespec_t* timer, timespec_t* deadline)
{
    if (timer == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "The timer argument cannot be NULL.");

    if (deadline == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "The deadline argument cannot be NULL.");

    if (timer->tv_nsec == 0 && timer->tv_sec == 0) {
        /* A zero timeout corresponds to a try-once attempt */
        deadline->tv_nsec = 0;
        deadline->tv_sec = 0;
        no_err_return(DRAGON_SUCCESS);
    }

    timespec_t current;

    clock_gettime(CLOCK_MONOTONIC, &current);

    dragon_timespec_add(deadline, &current, timer);

    no_err_return(DRAGON_SUCCESS);
}

/***************************************************************************************
 * Check whether the current time has past the end of a timer and compute remaining time.
 *
 * This function no_err_return(DRAGON_SUCCESS) if no timeout has occurred and computes the
 * remaining time. If deadline is in the past, then this function returns DRAGON_TIMEOUT.
 *
 * @param deadline A pointer to a timespec structure that holds the time when the timer
 * will expire.
 * @param remaining_timeout The computed remaining time for the given deadline.
 * @returns DRAGON_SUCCESS or DRAGON_TIMEOUT or an undetermined error code.
 **********************************************************************************/

dragonError_t
dragon_timespec_remaining(const timespec_t * deadline, timespec_t * remaining_timeout)
{
    timespec_t now_time;

    if (deadline == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "Cannot pass NULL as deadline argument.");

    if (remaining_timeout == NULL)
        err_return(DRAGON_INVALID_ARGUMENT, "Cannot pass NULL as remaining_timeout argument.");

    if (deadline->tv_nsec == 0 && deadline->tv_sec == 0) {
        /* A zero timeout corresponds to a try-once attempt */
        remaining_timeout->tv_nsec = 0;
        remaining_timeout->tv_sec = 0;
        no_err_return(DRAGON_SUCCESS);
    }

    clock_gettime(CLOCK_MONOTONIC, &now_time);

    if (dragon_timespec_le(deadline, &now_time)) {
        remaining_timeout->tv_sec = 0;
        remaining_timeout->tv_nsec = 0;
        no_err_return(DRAGON_TIMEOUT);
    }

    dragonError_t err = dragon_timespec_diff(remaining_timeout, deadline, &now_time);
    if (err != DRAGON_SUCCESS)
        append_err_return(err, "This shouldn't happen.");

    no_err_return(DRAGON_SUCCESS);
}

double dragon_get_current_time_as_double() {
    timespec_t the_time;
    clock_gettime(CLOCK_MONOTONIC, &the_time);
    double time_val = the_time.tv_sec + ((double)the_time.tv_nsec) / NSEC_PER_SECOND;
    return time_val;
}

void strip_newlines(const char* inout_str, size_t* input_length) {
    size_t idx = *input_length-1;

    while (inout_str[idx] == '\n')
        idx--;

    *input_length = idx+1;
}

static const char encoding_table[] = {
            'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H',
            'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P',
            'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X',
            'Y', 'Z', 'a', 'b', 'c', 'd', 'e', 'f',
            'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n',
            'o', 'p', 'q', 'r', 's', 't', 'u', 'v',
            'w', 'x', 'y', 'z', '0', '1', '2', '3',
            '4', '5', '6', '7', '8', '9', '+', '/' };

static const unsigned char decoding_table[256] = {
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3e, 0x00, 0x00, 0x00, 0x3f,
    0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x3b, 0x3c, 0x3d, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e,
    0x0f, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
    0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x32, 0x33, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };

char*
dragon_base64_encode(uint8_t *data, size_t input_length)
{

    const int mod_table[] = { 0, 2, 1 };

    size_t output_length = 4 * ((input_length + 2) / 3);

    char *encoded_data = (char*)malloc(1 + output_length);

    if (encoded_data == NULL)
        return NULL;

    for (int i = 0, j = 0; i < input_length;) {

        uint32_t octet_a = i < input_length ? (unsigned char)data[i++] : 0;
        uint32_t octet_b = i < input_length ? (unsigned char)data[i++] : 0;
        uint32_t octet_c = i < input_length ? (unsigned char)data[i++] : 0;

        uint32_t triple = (octet_a << 0x10) + (octet_b << 0x08) + octet_c;

        encoded_data[j++] = encoding_table[(triple >> 3 * 6) & 0x3F];
        encoded_data[j++] = encoding_table[(triple >> 2 * 6) & 0x3F];
        encoded_data[j++] = encoding_table[(triple >> 1 * 6) & 0x3F];
        encoded_data[j++] = encoding_table[(triple >> 0 * 6) & 0x3F];
    }

    for (int i = 0; i < mod_table[input_length % 3]; i++)
        encoded_data[output_length - 1 - i] = '=';

    encoded_data[output_length] = '\0';

    return encoded_data;
}

uint8_t*
dragon_base64_decode(const char *data, size_t *output_length)
{
    size_t input_length = strlen(data);

    strip_newlines(data, &input_length);

    if (input_length % 4 != 0)
        return NULL;


    *output_length = input_length / 4 * 3;

    if (data[input_length - 1] == '=') (*output_length)--;
    if (data[input_length - 2] == '=') (*output_length)--;

    uint8_t* decoded_data = (unsigned char*)malloc(*output_length);

    if (decoded_data == NULL)
        return NULL;

    for (int i = 0, j = 0; i < input_length;) {

        uint32_t sextet_a = data[i] == '=' ? 0 & i++ : decoding_table[(unsigned char)data[i++]];
        uint32_t sextet_b = data[i] == '=' ? 0 & i++ : decoding_table[(unsigned char)data[i++]];
        uint32_t sextet_c = data[i] == '=' ? 0 & i++ : decoding_table[(unsigned char)data[i++]];
        uint32_t sextet_d = data[i] == '=' ? 0 & i++ : decoding_table[(unsigned char)data[i++]];

        uint32_t triple = (sextet_a << 3 * 6)
            + (sextet_b << 2 * 6)
            + (sextet_c << 1 * 6)
            + (sextet_d << 0 * 6);

        if (j < *output_length) decoded_data[j++] = (triple >> 2 * 8) & 0xFF;
        if (j < *output_length) decoded_data[j++] = (triple >> 1 * 8) & 0xFF;
        if (j < *output_length) decoded_data[j++] = (triple >> 0 * 8) & 0xFF;

    }

    return decoded_data;

}

/* this is hash function based on splitmix64 from
http://xorshift.di.unimi.it/splitmix64.c */
dragonULInt
dragon_hash_ulint(dragonULInt x)
{
    dragonULInt z = (x += 0x9e3779b97f4a7c15);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9;
    z = (z ^ (z >> 27)) * 0x94d049bb133111eb;
    return z ^ (z >> 31);
}

dragonULInt
dragon_hash(void* ptr, size_t num_bytes)
{
    if (num_bytes == 0)
        return 0;

    if (ptr == NULL)
        return 0;

    size_t alignment = sizeof(dragonULInt) - ((dragonULInt)ptr) % sizeof(dragonULInt);
    if (alignment == sizeof(dragonULInt))
        alignment = 0;

    size_t num_words = (num_bytes-alignment)/sizeof(dragonULInt);

    size_t rem = (num_bytes-alignment)%sizeof(dragonULInt);

    uint8_t* first_bytes = (uint8_t*) ptr;
    dragonULInt* arr = (dragonULInt*) (first_bytes + alignment);
    uint8_t* last_bytes = (uint8_t*)&arr[num_words];

    dragonULInt hashVal = 0;

    long i;
    for (i=0;i<alignment;i++)
        hashVal = hashVal + first_bytes[i] * 0x9e3779b97f4a7c15;

    for (i=0;i<num_words;i++)
        hashVal = hashVal + arr[i] * 0xbf58476d1ce4e5b9;

    for (i=0;i<rem;i++)
        hashVal = hashVal + last_bytes[i] * 0x94d049bb133111eb;

    return hashVal;
}

bool
dragon_bytes_equal(void* ptr1, void* ptr2, size_t ptr1_numbytes, size_t ptr2_numbytes)
{
    /* It is assumed that each pointer points to a word boundary since memory allocations
       in Dragon always start on word boundaries. */

    if (ptr1_numbytes != ptr2_numbytes)
        return false;

    if (ptr1 == ptr2)
        return true;

    size_t num_words = ptr1_numbytes/sizeof(dragonULInt);
    size_t rem = ptr1_numbytes%sizeof(dragonULInt);
    dragonULInt* first = (dragonULInt*) ptr1;
    dragonULInt* second = (dragonULInt*) ptr2;

    for (size_t i=0;i<num_words;i++)
        if (first[i] != second[i])
            return false;

    uint8_t* first_bytes = (uint8_t*)&first[num_words];
    uint8_t* second_bytes = (uint8_t*)&second[num_words];

    for (size_t i=0;i<rem;i++)
        if (first_bytes[i] != second_bytes[i])
            return false;

    return true;
}

uint64_t
dragon_sec_to_nsec(uint64_t sec)
{
    return sec * 1e9;
}

void
dragon_set_thread_local_mode(bool set_thread_local)
{
    _set_thread_local_mode_channels(set_thread_local);
    _set_thread_local_mode_channelsets(set_thread_local);
    _set_thread_local_mode_managed_memory(set_thread_local);
    _set_thread_local_mode_bcast(set_thread_local);
    _set_thread_local_mode_ddict(set_thread_local);
    _set_thread_local_mode_fli(set_thread_local);
    _set_thread_local_mode_queues(set_thread_local);

    dg_thread_local_mode = set_thread_local;
}

bool
dragon_get_thread_local_mode()
{
    return dg_thread_local_mode;
}

