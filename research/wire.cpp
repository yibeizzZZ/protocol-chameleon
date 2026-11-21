// SPDX-License-Identifier: Apache-2.0
// A physical-pin transactor. All decisions and data reads use top-level ports.
#include "Vwire.h"
#include "poll_image.h"
#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace {
enum Counter { Clocks, Resets, Writes, Runs, Frames, Pages, ResetClocks,
               LastA, LastB, LastRun, LastDone, CounterCount };
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
bool gap_ok(int n) { return n == 0 || n == 16 || n == 64 || n == 128; }
bool byte_ok(int n) { return n >= 0 && n < 256; }

struct Wire {
    VerilatedContext context;
    Vwire dut;
    unsigned inputs = 2, peer_oe = 0x0b;
    std::array<uint64_t, CounterCount> counts{};
    std::array<int, 256> fields{};
    bool loaded = false, monitoring = false;
    int previous_irq = 0, announced = 0, consumed = 0;
    std::array<int, 2> gaps{};
    std::string error;

    Wire() : context(), dut(single_thread()) {}
    VerilatedContext* single_thread() { context.threads(1); return &context; }
    ~Wire() { dut.final(); }

    unsigned pads() const {
        return (inputs & peer_oe) | (dut.uio_out & dut.uio_oe);
    }
    void settle() {
        // Undriven pins resolve to zero in the two-state model. MISO samples
        // explicitly require active output enable, and overlap fails each tick.
        for (int i = 0; i < 4; ++i) {
            dut.uio_in = pads();
            dut.eval();
            if (dut.uio_in == pads()) return;
        }
        throw std::runtime_error("pad resolution did not settle");
    }
    void tick(int n = 1) {
        for (int i = 0; i < n; ++i) {
            dut.clk = 0;
            settle();
            dut.clk = 1;
            settle();
            require(!(dut.uio_oe & peer_oe), "peer/DUT output-enable overlap");
            ++counts[Clocks];
            if (!monitoring) continue;
            int irq = dut.uo_out & 3;
            int rises = irq & ~previous_irq;
            if (rises & 1) counts[LastA] = counts[Clocks];
            if (rises & 2) counts[LastB] = counts[Clocks];
            if (irq == 3 && previous_irq != 3) {
                require(announced < 2, "unexpected simultaneous notification");
                gaps[announced++] = int(counts[LastB] - counts[LastA]);
            }
            previous_irq = irq;
            if ((dut.uo_out & 15) == 8) {
                monitoring = false;
                counts[LastDone] = counts[Clocks];
            }
        }
    }
    void write(int byte, bool control = true) {
        dut.ui_in = byte;
        inputs = (inputs & ~9u) | (control ? 8 : 0);
        tick();
        inputs |= 1;
        tick();
        ++counts[Writes];
    }
    void field(int selector, int value) {
        write(selector);
        write(value, false);
        fields[selector] = value;
    }
    void change(int selector, int value) {
        if (fields[selector] != value) field(selector, value);
    }
    void reset_load() {
        monitoring = loaded = false;
        inputs = 2;
        peer_oe = 0x0b;
        dut.ui_in = 0;
        dut.ena = 1;
        dut.rst_n = 0;
        tick(2);
        dut.rst_n = 1;
        tick();
        ++counts[Resets];
        counts[ResetClocks] += 3;
        require(dut.uo_out == 1 && dut.uio_out == 0 && dut.uio_oe == 0xf4,
                "unexpected reset outputs");
        fields.fill(0);
        write(0);
        write(0x83);
        require(dut.uio_oe == 4, "engine entry failed");
        write(1);
        for (int byte : image) write(byte, false);
        for (auto &pair : settings) field(pair[0], pair[1]);
        write(program_run);
        inputs |= 0x10;
        peer_oe |= 0x70;
        tick(5);
        write(0x10);
        write(0x30);
        // Length three, quota one, no A comparison. B compares annotated
        // command (byte 2) to 0x55. Both absolute deadline ticks are 1000.
        for (int slot = 0; slot < 2; ++slot) {
            int descriptor[] = {slot ? 0x29 : 0x21, slot ? 0x55 : 0xa6,
                                0, 0, 0, 1000 & 255, 1000 >> 8};
            for (int i = 0; i < 7; ++i) field(0x40 + 8*slot + i, descriptor[i]);
        }
        field(0x50, 0);
        field(0x5a, 1);    // bind tag 1 (poll), field CMD
        field(0x5b, 0x88);
        field(0x5c, 1);    // recognize opcode 1 in operand 0
        field(0x60, 0x21); // PASS only, any history, select profile 1
        field(0x62, 1);
        loaded = true;
    }
    void setup(int trials, int first_gap, int second_gap, int seed,
               int second, int adaptive) {
        require(loaded && !monitoring, "setup requires an idle loaded chip");
        require((trials == 1 || trials == 2) && gap_ok(first_gap) && gap_ok(second_gap)
                && byte_ok(seed) && byte_ok(second) && (adaptive == 0 || adaptive == 1),
                "invalid trial plan");
        int edit = 0;
        if (trials == 2) {
            if (adaptive) edit = 0xe0;
            else if (seed != second) {
                int delta = (second - seed + 256) % 256;
                require(delta < 16 || delta >= 240, "second byte outside signed ADD range");
                edit = 0xc0 | (delta & 31);
            }
            change(0x75, second_gap);
            change(0x63, edit);
        }
        change(0x71, first_gap);
        change(0x5d, seed);
        change(0x51, trials - 1);
    }
    void run() {
        require(loaded && !monitoring, "RUN requires an idle loaded chip");
        write(0x34);
        require((dut.uo_out & 12) == 4, "RUN not accepted");
        ++counts[Runs];
        counts[LastRun] = counts[Clocks];
        counts[LastDone] = counts[LastA] = counts[LastB] = 0;
        previous_irq = announced = consumed = 0;
        monitoring = true;
        tick(); // checker START, matching the public launch helper
    }
    int wait(int* gap) {
        require(gap != nullptr, "missing gap output");
        for (int i = 0; i < 2100; ++i) {
            if (consumed < announced) {
                *gap = gaps[consumed++];
                return 1;
            }
            if (!monitoring) {
                require((dut.uo_out & 15) == 8, "wait without RUN");
                return 0;
            }
            tick();
        }
        throw std::runtime_error("notification wait timed out");
    }
    int frame(int slot, int request) {
        require((slot == 0 || slot == 1) && request >= 0 && request <= 0xffffff,
                "bad slot or frame");
        require(loaded && consumed > 0 && dut.ui_in == 0x34, "frame requires an issued trial");
        unsigned cs = slot ? 2 : 0x10;
        inputs &= ~cs;
        int reply = 0, sent = 0;
        for (int bit = 23; bit >= 0; --bit) {
            inputs = (inputs & ~0x60u) | (((request >> bit) & 1) << 6);
            tick(5);
            require((dut.uio_oe & 0x80) && (pads() & 0x12) == (0x12 ^ cs),
                    "MISO undriven or chip select invalid at sample");
            reply = (reply << 1) | ((pads() >> 7) & 1);
            sent = (sent << 1) | ((pads() >> 6) & 1);
            inputs |= 0x20;
            tick(5);
        }
        inputs &= ~0x20u;
        tick(5);
        inputs |= cs;
        tick(5);
        require(sent == request, "MOSI mismatch on wire");
        ++counts[Frames];
        return reply;
    }
};

template<class F> int checked(Wire* w, F op) {
    if (!w) return -1;
    try { return op(); }
    catch (const std::exception& ex) { w->error = ex.what(); return -1; }
}
}  // namespace

extern "C" {
Wire* wire_new() { try { return new Wire; } catch (...) { return nullptr; } }
void wire_free(Wire* w) { delete w; }
const char* wire_error(Wire* w) { return w ? w->error.c_str() : "null chip"; }
int wire_reset_load(Wire* w) { return checked(w, [&]{ w->reset_load(); return 0; }); }
int wire_setup(Wire* w, int n, int g1, int g2, int b1, int b2, int adaptive) {
    return checked(w, [&]{ w->setup(n,g1,g2,b1,b2,adaptive); return 0; });
}
int wire_run(Wire* w) { return checked(w, [&]{ w->run(); return 0; }); }
int wire_wait(Wire* w, int* gap) { return checked(w, [&]{ return w->wait(gap); }); }
int wire_frame(Wire* w, int slot, int mosi) {
    return checked(w, [&]{ return w->frame(slot,mosi); });
}
int wire_done(Wire* w) {
    return checked(w, [&]{
        for (int i = 0; w->monitoring && i < 2100; ++i) w->tick();
        require((w->dut.uo_out & 15) == 8, "DONE wait timed out");
        return 0;
    });
}
int wire_idle(Wire* w, int clocks) {
    return checked(w, [&]{
        require(clocks >= 0 && !w->monitoring, "idle requires completed RUN");
        w->tick(clocks);
        return 0;
    });
}
int wire_page(Wire* w, int address) {
    return checked(w, [&]{
        require(byte_ok(address) && !w->monitoring && (w->dut.uo_out & 15) == 8,
                "readback requires DONE");
        w->dut.ui_in = address;
        w->tick();
        ++w->counts[Pages];
        return w->dut.uo_out >> 4;
    });
}
uint64_t wire_count(Wire* w, int counter) {
    return w && counter >= 0 && counter < CounterCount ? w->counts[counter] : UINT64_MAX;
}
}
