import io
import wave
import av


def normalize_audio(file, max_seconds=3600):
    pcm = io.BytesIO()
    with av.open(file, mode='r') as container:
        if not container.streams.audio:
            raise ValueError('No audio')
        resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        for frame in container.decode(container.streams.audio[0]):
            for converted in resampler.resample(frame):
                pcm.write(converted.to_ndarray().tobytes())
                if pcm.tell() > max_seconds * 32000:
                    raise ValueError('Too long')
        for converted in resampler.resample(None):
            pcm.write(converted.to_ndarray().tobytes())
    data = pcm.getvalue()
    if not 3200 <= len(data) <= max_seconds * 32000:
        raise ValueError('Invalid duration')
    count = (len(data) + 600 * 32000 - 1) // (600 * 32000)
    frames = len(data) // 2
    for part in range(count):
        start, end = frames * part // count, frames * (part + 1) // count
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(data[start * 2:end * 2])
        yield start / 16000, output.getvalue()
