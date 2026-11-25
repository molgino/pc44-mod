// SPDX-License-Identifier: MIT
// A duplex USB device for the native plugin integration test.
#include <alsa/asoundlib.h>

#include <atomic>
#include <cassert>
#include <deque>
#include <mutex>
#include <vector>

struct _snd_seq { bool subscribed = false; };
struct _snd_seq_client_info { int id = -1; };
struct _snd_seq_port_info { int client = -1; int port = -1; };

namespace {
constexpr int Device = 24;
constexpr int MidiPort = 0;
constexpr int EditorPort = 1;
struct Frame { std::vector<uint8_t> bytes; int client; };
std::mutex mutex;
std::deque<Frame> incoming;
std::deque<std::vector<uint8_t>> outgoing;
std::atomic<bool> attached{true};
}

extern "C" {

void fake_attach(bool enabled) { attached.store(enabled); }

void fake_emit(const uint8_t* bytes, std::size_t size, int client)
{
    std::lock_guard<std::mutex> lock(mutex);
    incoming.push_back({{bytes, bytes + size}, client});
}

int fake_command(uint8_t* bytes)
{
    std::lock_guard<std::mutex> lock(mutex);
    if (outgoing.empty()) return 0;
    const int size = outgoing.front().size();
    std::copy(outgoing.front().begin(), outgoing.front().end(), bytes);
    outgoing.pop_front();
    return size;
}

int snd_seq_open(snd_seq_t** seq, const char*, int streams, int mode)
{
    assert(streams == SND_SEQ_OPEN_DUPLEX && mode == SND_SEQ_NONBLOCK);
    *seq = new snd_seq_t;
    return 0;
}
int snd_seq_close(snd_seq_t* seq) { delete seq; return 0; }
int snd_seq_set_client_name(snd_seq_t*, const char*) { return 0; }

int snd_seq_create_simple_port(snd_seq_t*, const char*, unsigned int caps, unsigned int)
{
    assert(caps & SND_SEQ_PORT_CAP_WRITE);
    return EditorPort;
}
int snd_seq_connect_from(snd_seq_t* seq, int local, int client, int port)
{
    assert(local == EditorPort && client == Device && port == MidiPort);
    seq->subscribed = true;
    return 0;
}
int snd_seq_disconnect_from(snd_seq_t* seq, int, int, int)
{
    seq->subscribed = false;
    return 0;
}

int snd_seq_client_info_malloc(snd_seq_client_info_t** c) { *c = new snd_seq_client_info_t; return 0; }
void snd_seq_client_info_free(snd_seq_client_info_t* c) { delete c; }
void snd_seq_client_info_set_client(snd_seq_client_info_t* c, int id) { c->id = id; }
int snd_seq_client_info_get_client(const snd_seq_client_info_t* c) { return c->id; }
const char* snd_seq_client_info_get_name(snd_seq_client_info_t*) { return "Faderfox PC44"; }
snd_seq_client_type_t snd_seq_client_info_get_type(const snd_seq_client_info_t* c)
{
    return c->id == Device ? SND_SEQ_KERNEL_CLIENT : SND_SEQ_USER_CLIENT;
}
int snd_seq_query_next_client(snd_seq_t*, snd_seq_client_info_t* c)
{
    // Also advertise a similarly-named user client. The editor must skip it.
    if (attached.load() && c->id < Device) { c->id = Device; return 0; }
    if (c->id < 128) { c->id = 128; return 0; }
    return -ENOENT;
}

int snd_seq_port_info_malloc(snd_seq_port_info_t** p) { *p = new snd_seq_port_info_t; return 0; }
void snd_seq_port_info_free(snd_seq_port_info_t* p) { delete p; }
void snd_seq_port_info_set_client(snd_seq_port_info_t* p, int client) { p->client = client; }
void snd_seq_port_info_set_port(snd_seq_port_info_t* p, int port) { p->port = port; }
int snd_seq_port_info_get_port(const snd_seq_port_info_t* p) { return p->port; }
const char* snd_seq_port_info_get_name(const snd_seq_port_info_t*) { return "USB MIDI"; }
unsigned int snd_seq_port_info_get_capability(const snd_seq_port_info_t*)
{
    return SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ | SND_SEQ_PORT_CAP_WRITE;
}
unsigned int snd_seq_port_info_get_type(const snd_seq_port_info_t*) { return SND_SEQ_PORT_TYPE_HARDWARE; }
int snd_seq_query_next_port(snd_seq_t*, snd_seq_port_info_t* p)
{
    if (p->port >= MidiPort) return -ENOENT;
    p->port = MidiPort;
    return 0;
}

int snd_seq_event_input(snd_seq_t* seq, snd_seq_event_t** event)
{
    std::lock_guard<std::mutex> lock(mutex);
    if (!seq->subscribed || incoming.empty() || !attached.load()) return -EAGAIN;
    static thread_local std::vector<uint8_t> bytes;
    static thread_local snd_seq_event_t current;
    bytes = std::move(incoming.front().bytes);
    current = {};
    current.source.client = incoming.front().client;
    current.source.port = MidiPort;
    snd_seq_ev_set_sysex(&current, bytes.size(), bytes.data());
    incoming.pop_front();
    *event = &current;
    return incoming.size();
}

int snd_seq_event_output_direct(snd_seq_t*, snd_seq_event_t* event)
{
    assert(attached.load());
    assert(event->source.port == EditorPort && event->dest.client == Device && event->dest.port == MidiPort);
    assert(event->type == SND_SEQ_EVENT_SYSEX && event->queue == SND_SEQ_QUEUE_DIRECT);
    const auto* data = static_cast<const uint8_t*>(event->data.ext.ptr);
    std::lock_guard<std::mutex> lock(mutex);
    outgoing.emplace_back(data, data + event->data.ext.len);
    return 1;
}
}
