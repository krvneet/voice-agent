/* Minimal LiveKit voice client (vanilla JS, no framework).
   Uses the vendored livekit-client UMD bundle (global `LivekitClient`). */

const { Room, RoomEvent, Track } = LivekitClient;

const els = {
  toggle: document.getElementById("toggle"),
  status: document.getElementById("status"),
  orb: document.getElementById("orb"),
  transcript: document.getElementById("transcript"),
  audio: (() => {
    const d = document.createElement("div");
    d.style.display = "none";
    document.body.appendChild(d);
    return d;
  })(),
};

let room = null;
// track interim transcript segments by id so we can replace them on final
const segments = new Map();

function setStatus(text) { els.status.textContent = text; }
function setOrb(state) { els.orb.dataset.state = state; }

function renderSegment(id, who, text, final) {
  let line = segments.get(id);
  if (!line) {
    line = document.createElement("div");
    line.className = `line ${who}`;
    line.innerHTML = `<span class="who">${who === "user" ? "You" : "Assistant"}</span><span class="txt"></span>`;
    els.transcript.appendChild(line);
    segments.set(id, line);
  }
  line.classList.toggle("interim", !final);
  line.querySelector(".txt").textContent = text;
  els.transcript.scrollTop = els.transcript.scrollHeight;
}

async function connect() {
  els.toggle.disabled = true;
  setStatus("Connecting…");
  setOrb("connecting");

  let data;
  try {
    const res = await fetch("/token");
    data = await res.json();
  } catch (e) {
    setStatus("Could not reach the server.");
    setOrb("idle");
    els.toggle.disabled = false;
    return;
  }

  room = new Room({ adaptiveStream: true, dynacast: true });

  // Play the agent's audio automatically.
  room.on(RoomEvent.TrackSubscribed, (track) => {
    if (track.kind === Track.Kind.Audio) {
      els.audio.appendChild(track.attach());
    }
  });

  // Handle browser autoplay gating.
  room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
    if (!room.canPlaybackAudio) room.startAudio();
  });

  // Reflect agent speaking / user listening in the orb.
  room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
    const agentSpeaking = speakers.some((p) => p.identity !== room.localParticipant.identity);
    if (room.state === "connected") setOrb(agentSpeaking ? "speaking" : "listening");
  });

  room.on(RoomEvent.Disconnected, () => teardown());

  // Live transcriptions (agent + user) via the text-stream topic.
  room.registerTextStreamHandler("lk.transcription", async (reader, participant) => {
    const attrs = reader.info.attributes || {};
    const id = attrs["lk.segment_id"] || reader.info.id;
    const isUser = !!attrs["lk.transcribed_track_id"] &&
      participant?.identity === room.localParticipant.identity;
    const who = isUser ? "user" : "agent";
    for await (const chunk of reader) {
      const final = attrs["lk.transcription_final"] === "true";
      renderSegment(id, who, chunk, final);
    }
  });

  try {
    await room.connect(data.url, data.token);
    await room.localParticipant.setMicrophoneEnabled(true);
  } catch (e) {
    setStatus("Connection failed. Check mic permissions.");
    return teardown();
  }

  setStatus("Listening… speak whenever you're ready.");
  setOrb("listening");
  els.toggle.textContent = "Disconnect";
  els.toggle.dataset.connected = "true";
  els.toggle.disabled = false;
}

function teardown() {
  if (room) { room.disconnect(); room = null; }
  segments.clear();
  setStatus("Disconnected.");
  setOrb("idle");
  els.toggle.textContent = "Connect";
  els.toggle.dataset.connected = "false";
  els.toggle.disabled = false;
}

els.toggle.addEventListener("click", () => {
  if (room) teardown();
  else connect();  // user gesture → satisfies mic permission + audio autoplay
});
