# The Wine tests' image with a sound clock that runs in real time, for the runs that judge a song's frames against its
# music (gpu/song.sh). The tests' sound is otherwise ALSA's null device, which takes the game's sound as fast as it is
# written: its play cursor runs ahead of real time, and the in-game layer's music lock drags a song's frames to 65 to 79
# a second after it. Here the sound goes to PulseAudio's null sink, which plays it out at the sound card's own rate:
# through ALSA's pulse plugin where Wine has no PulseAudio driver of its own (the GPU image's Wine, built without it),
# or through Wine's own PulseAudio driver where it has one (the CPU image's). Nothing is heard: the sink is null.
#
#   docker build -t opendmt3-wine-gpu-sound:local --build-arg BASE=opendmt3-wine-gpu:local tests/e2e/windows/gpu/sound
ARG BASE=opendmt3-wine-gpu:local
FROM ${BASE}
# The sound server, its tools (pactl to make the null sink the default) and ALSA's plugins (its pulse device).
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
      pulseaudio pulseaudio-utils libasound2-plugins >/dev/null \
    && rm -rf /var/lib/apt/lists/*
