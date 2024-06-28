If you edit raw video, use this script. The main script is for edited video but the pacing is so slow

import subprocess
import os
import contextlib
import wave
import collections
import webrtcvad

def get_frame_rate(video_path):
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
           '-show_entries', 'stream=r_frame_rate', '-of', 'default=noprint_wrappers=1:nokey=1', video_path]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise Exception(f"ffprobe error: {stderr.decode()}")

    try:
        fps = stdout.decode().strip().split('/')
        if len(fps) == 2:
            return float(fps[0]) / float(fps[1])
        return float(fps[0])
    except ValueError as e:
        raise ValueError(f"Could not parse frame rate: {fps}") from e

def extract_audio(video_path):
    output_audio_path = os.path.splitext(video_path)[0] + '.wav'
    cmd = ['ffmpeg', '-i', video_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', output_audio_path]
    subprocess.run(cmd, check=True)
    return output_audio_path

def read_wave(path):
    with contextlib.closing(wave.open(path, 'rb')) as wf:
        num_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        pcm_data = wf.readframes(wf.getnframes())
        return pcm_data, sample_width, sample_rate

def frame_generator(frame_duration_ms, audio, sample_rate):
    n = int(sample_rate * (frame_duration_ms / 1000.0) * 2)
    offset = 0
    timestamp = 0.0
    duration = float(n) / sample_rate / 2
    while offset + n < len(audio):
        yield audio[offset:offset + n], timestamp, duration
        timestamp += duration
        offset += n

def vad_collector(sample_rate, frame_duration_ms, padding_duration_ms, vad, frames):
    num_padding_frames = int(padding_duration_ms / frame_duration_ms)
    ring_buffer = collections.deque(maxlen=num_padding_frames)
    triggered = False
    voiced_frames = []
    pre_buffer_time = 0.2  # 200 ms buffer
    for frame, timestamp, duration in frames:
        is_speech = vad.is_speech(frame, sample_rate)
        if not triggered:
            ring_buffer.append((frame, is_speech, timestamp, duration))
            num_voiced = len([f for f, s, t, d in ring_buffer if s])
            if num_voiced > 0.9 * ring_buffer.maxlen:
                triggered = True
                start_time = max(0, ring_buffer[0][2] - pre_buffer_time)  # Apply pre-buffer
                voiced_frames.append((start_time, timestamp + duration))
                ring_buffer.clear()
        else:
            voiced_frames.append((timestamp, timestamp + duration))
            ring_buffer.append((frame, is_speech, timestamp, duration))
            num_unvoiced = len([f for f, s, t, d in ring_buffer if not s])
            if num_unvoiced > 0.9 * ring_buffer.maxlen:
                triggered = False
                yield voiced_frames
                ring_buffer.clear()
                voiced_frames = []
    if voiced_frames:
        yield voiced_frames

def get_speech_segments(audio_path):
    audio, sample_width, sample_rate = read_wave(audio_path)
    vad = webrtcvad.Vad(2)  # Set to mode 2 for aggressive VAD
    frames = frame_generator(30, audio, sample_rate)
    segments = vad_collector(sample_rate, 30, 300, vad, frames)
    segments = [seg for seg_list in segments for seg in seg_list]
    return segments

def cut_video_with_ffmpeg(video_path, output_path, segments, frame_rate):
    filters = []
    for i, (start, end) in enumerate(segments):
        start = round(start, 3)  # Maintain precision and avoid snapping to keyframes if not necessary
        end = round(end, 3)
        filters.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];")
        filters.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];")

    video_filters = ''.join(f"[v{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[v];"
    audio_filters = ''.join(f"[a{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=0:a=1[a];"
    filter_complex = "".join(filters) + video_filters + audio_filters

    cmd = ['ffmpeg', '-i', video_path, '-filter_complex', filter_complex, '-map', '[a]', '-map', '[v]', '-r', str(frame_rate), output_path]
    subprocess.run(cmd, check=True)

def process_folder(folder_path):
    for filename in os.listdir(folder_path):
        if filename.endswith(".mp4"):
            video_path = os.path.join(folder_path, filename)
            frame_rate = get_frame_rate(video_path)
            audio_path = extract_audio(video_path)
            segments = get_speech_segments(audio_path)
            os.remove(audio_path)
            output_path = os.path.join(folder_path, f"{os.path.splitext(filename)[0]}_cut.mp4")
            cut_video_with_ffmpeg(video_path, output_path, segments, frame_rate)

# Example usage
folder_path = "/Users/anh/Desktop/face"
process_folder(folder_path)