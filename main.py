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
    fps = stdout.decode().strip().split('/')
    return float(fps[0]) / float(fps[1]) if len(fps) == 2 else float(fps[0])

def extract_audio(video_path):
    output_audio_path = os.path.splitext(video_path)[0] + '.wav'
    cmd = ['ffmpeg', '-y', '-i', video_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', output_audio_path]
    subprocess.run(cmd, check=True)
    return output_audio_path

def read_wave(path):
    with contextlib.closing(wave.open(path, 'rb')) as wf:
        return wf.readframes(wf.getnframes()), wf.getsampwidth(), wf.getframerate()

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
    for frame, timestamp, duration in frames:
        is_speech = vad.is_speech(frame, sample_rate)
        if not triggered:
            ring_buffer.append((frame, is_speech, timestamp, duration))
            if is_speech:
                triggered = True
                start_time = timestamp
                for f, s, t, d in ring_buffer:
                    if s: voiced_frames.append((t, t + d))
                ring_buffer.clear()
        else:
            if not is_speech:
                end_time = timestamp + duration
                triggered = False
                yield (start_time, end_time)
            else:
                voiced_frames.append((timestamp, timestamp + duration))
    if triggered:
        yield (start_time, timestamp + duration)

def get_speech_segments(audio_path, aggressiveness=3):  # Set aggressiveness to the highest level
    audio, sample_width, sample_rate = read_wave(audio_path)
    vad = webrtcvad.Vad(aggressiveness)
    frames = frame_generator(30, audio, sample_rate)
    segments = list(vad_collector(sample_rate, 30, 300, vad, frames))
    return segments

def cut_video_with_ffmpeg(video_path, output_path, segments, frame_rate):
    if not segments:
        print("No segments to concatenate, exporting full video.")
        subprocess.run(['ffmpeg', '-y', '-i', video_path, '-c', 'copy', output_path], check=True)
        return
    filters = []
    for i, (start, end) in enumerate(segments):
        filters.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];")
        filters.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];")
    video_filters = ''.join(f"[v{i}]" for i in range(len(segments))) + "concat=n={}:v=1:a=0[v];".format(len(segments))
    audio_filters = ''.join(f"[a{i}]" for i in range(len(segments))) + "concat=n={}:v=0:a=1[a];".format(len(segments))
    filter_complex = "".join(filters) + video_filters + audio_filters
    cmd = ['ffmpeg', '-y', '-i', video_path, '-filter_complex', filter_complex, '-map', '[v]', '-map', '[a]', '-r', str(frame_rate), output_path]
    subprocess.run(cmd, check=True)

def process_folder(folder_path):
    output_folder = os.path.join(folder_path, "auto_cut_videos")
    os.makedirs(output_folder, exist_ok=True)

    for filename in os.listdir(folder_path):
        if filename.endswith(".mp4"):
            try:
                video_path = os.path.join(folder_path, filename)
                frame_rate = get_frame_rate(video_path)
                audio_path = extract_audio(video_path)
                segments = get_speech_segments(audio_path, aggressiveness=3)  # Set aggressiveness to the highest level
                os.remove(audio_path)  # Clean up the extracted audio file
                output_path = os.path.join(output_folder, os.path.splitext(filename)[0] + "_cut.mp4")
                cut_video_with_ffmpeg(video_path, output_path, segments, frame_rate)
                print(f"Processed {filename} successfully.")
            except Exception as e:
                print(f"Error processing {filename}: {e}")

folder_path = "/Users/anh/Desktop/face"
process_folder(folder_path)
