// SPDX-License-Identifier: MIT
#pragma once

#include "Protocol.h"
#include <cstring>

#if defined(__linux__)
#include <alsa/asoundlib.h>
#include <dlfcn.h>
#include <strings.h>
#endif

namespace pc44 {

// USB traffic goes directly to the ALSA sequencer. The MPC's VST output
// callback ignores plug-in MIDI output, including SysEx.
class AlsaMidi {
public:
    enum class State { Unavailable, Missing, Multiple, ReadOnly, Duplex };
    ~AlsaMidi() { close(); }

#if defined(__linux__)
    State refresh()
    {
        if (!seq_ && !open()) return State::Unavailable;

        snd_seq_client_info_t* client;
        snd_seq_port_info_t* port;
        if (snd_seq_client_info_malloc_(&client) < 0) return State::Unavailable;
        if (snd_seq_port_info_malloc_(&port) < 0) {
            snd_seq_client_info_free_(client);
            return State::Unavailable;
        }

        const unsigned read = SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ;
        int foundClient = -1;
        int foundPort = -1;
        bool canWrite = false;
        bool multiple = false;
        snd_seq_client_info_set_client_(client, -1);
        while (snd_seq_query_next_client_(seq_, client) >= 0) {
            if (snd_seq_client_info_get_type_(client) != SND_SEQ_KERNEL_CLIENT) continue;
            const int id = snd_seq_client_info_get_client_(client);
            const bool isNamed = hasName(snd_seq_client_info_get_name_(client));
            snd_seq_port_info_set_client_(port, id);
            snd_seq_port_info_set_port_(port, -1);
            while (snd_seq_query_next_port_(seq_, port) >= 0) {
                const auto type = snd_seq_port_info_get_type_(port);
                const auto caps = snd_seq_port_info_get_capability_(port);
                if (!(type & SND_SEQ_PORT_TYPE_HARDWARE) || (caps & read) != read) continue;
                if (!isNamed && !hasName(snd_seq_port_info_get_name_(port))) continue;
                if (foundClient >= 0) multiple = true;
                foundClient = id;
                foundPort = snd_seq_port_info_get_port_(port);
                canWrite = (caps & SND_SEQ_PORT_CAP_WRITE) != 0;
            }
        }
        snd_seq_port_info_free_(port);
        snd_seq_client_info_free_(client);

        if (!multiple && foundClient == remoteClient_ && foundPort == remotePort_ && foundClient >= 0)
            return canWrite ? State::Duplex : State::ReadOnly;

        detach();
        if (multiple) return State::Multiple;
        if (foundClient < 0 || snd_seq_connect_from_(seq_, localPort_, foundClient, foundPort) < 0)
            return State::Missing;
        remoteClient_ = foundClient;
        remotePort_ = foundPort;
        return canWrite ? State::Duplex : State::ReadOnly;
    }

    template<typename Receive>
    bool poll(Receive receive)
    {
        if (!seq_) return true;
        for (int i = 0; i < 128; ++i) {
            snd_seq_event_t* event = nullptr;
            int result = snd_seq_event_input_(seq_, &event);
            if (result == -EAGAIN || result == -EINTR) return true;
            if (result < 0) return false;
            if (!event) break;
            if (event->type == SND_SEQ_EVENT_SYSEX && event->source.client == remoteClient_ &&
                event->source.port == remotePort_ && event->data.ext.ptr) {
                framer_.append(static_cast<const uint8_t*>(event->data.ext.ptr),
                               event->data.ext.len, receive);
            }
        }
        return true;
    }

    bool send(const Edit& edit)
    {
        if (remoteClient_ < 0) return false;
        auto bytes = edit.packet();
        snd_seq_event_t event{};
        snd_seq_ev_set_source(&event, localPort_);
        snd_seq_ev_set_dest(&event, remoteClient_, remotePort_);
        snd_seq_ev_set_direct(&event);
        snd_seq_ev_set_sysex(&event, edit.size(), bytes.data());
        return snd_seq_event_output_direct_(seq_, &event) >= 0;
    }

    void detach()
    {
        if (remoteClient_ >= 0)
            snd_seq_disconnect_from_(seq_, localPort_, remoteClient_, remotePort_);
        remoteClient_ = -1;
        remotePort_ = -1;
        framer_.reset();
    }

    void close()
    {
        detach();
        if (seq_) snd_seq_close_(seq_);
        seq_ = nullptr;
        if (lib_) dlclose(lib_);
        lib_ = nullptr;
    }

    int address() const { return remoteClient_ < 0 ? -1 : remoteClient_ * 256 + remotePort_; }

private:
    // Using libasound from the MPC avoids linking to the build host's ALSA
    // version. Only symbols present on both arm versions of MPC OS are used.
#define PC44_ALSA_FUNCTIONS(F)                          \
    F(snd_seq_open)                                    \
    F(snd_seq_close)                                   \
    F(snd_seq_set_client_name)                         \
    F(snd_seq_create_simple_port)                     \
    F(snd_seq_connect_from)                            \
    F(snd_seq_disconnect_from)                         \
    F(snd_seq_client_info_malloc)                     \
    F(snd_seq_client_info_free)                       \
    F(snd_seq_client_info_set_client)                 \
    F(snd_seq_client_info_get_client)                 \
    F(snd_seq_client_info_get_name)                   \
    F(snd_seq_client_info_get_type)                   \
    F(snd_seq_query_next_client)                      \
    F(snd_seq_port_info_malloc)                        \
    F(snd_seq_port_info_free)                          \
    F(snd_seq_port_info_set_client)                    \
    F(snd_seq_port_info_set_port)                      \
    F(snd_seq_port_info_get_port)                      \
    F(snd_seq_port_info_get_name)                      \
    F(snd_seq_port_info_get_type)                      \
    F(snd_seq_port_info_get_capability)                \
    F(snd_seq_query_next_port)                         \
    F(snd_seq_event_input)                             \
    F(snd_seq_event_output_direct)

#define DECLARE(F) decltype(&F) F##_ = nullptr;
    PC44_ALSA_FUNCTIONS(DECLARE)
#undef DECLARE

    bool open()
    {
        lib_ = dlopen("libasound.so.2", RTLD_NOW | RTLD_LOCAL);
        if (!lib_) return false;
#define LOAD(F) F##_ = reinterpret_cast<decltype(F##_)>(dlsym(lib_, #F)); if (!F##_) { close(); return false; }
        PC44_ALSA_FUNCTIONS(LOAD)
#undef LOAD
#undef PC44_ALSA_FUNCTIONS
        if (snd_seq_open_(&seq_, "default", SND_SEQ_OPEN_DUPLEX, SND_SEQ_NONBLOCK) < 0) {
            seq_ = nullptr;
            close();
            return false;
        }
        snd_seq_set_client_name_(seq_, "PC44 Editor");
        localPort_ = snd_seq_create_simple_port_(seq_, "Monitor", SND_SEQ_PORT_CAP_WRITE | SND_SEQ_PORT_CAP_SUBS_WRITE,
            SND_SEQ_PORT_TYPE_APPLICATION);
        if (localPort_ >= 0) return true;
        close();
        return false;
    }

    static bool hasName(const char* name)
    {
        for (; name && std::strlen(name) >= 4; ++name)
            if (strncasecmp(name, "PC44", 4) == 0) return true;
        return false;
    }

    void* lib_ = nullptr;
    snd_seq_t* seq_ = nullptr;
    int localPort_ = -1;
    int remoteClient_ = -1;
    int remotePort_ = -1;
    Framer framer_;
#else
    State refresh() { return State::Unavailable; }
    template<typename Receive> bool poll(Receive) { return true; }
    bool send(const Edit&) { return false; }
    void detach() {}
    void close() {}
    int address() const { return -1; }
#endif
};

} // namespace pc44
