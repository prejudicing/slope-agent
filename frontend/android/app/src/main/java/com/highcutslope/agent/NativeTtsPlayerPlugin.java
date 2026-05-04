package com.highcutslope.agent;

import android.media.MediaPlayer;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.util.Locale;
import java.util.UUID;

@CapacitorPlugin(name = "NativeTtsPlayer")
public class NativeTtsPlayerPlugin extends Plugin implements TextToSpeech.OnInitListener {

    private TextToSpeech tts;
    private MediaPlayer mediaPlayer;
    private boolean initialized = false;
    private boolean paused = false;
    private File currentAudioFile;
    private float currentVolume = 1.0f;

    @Override
    public void load() {
        super.load();
        Handler handler = new Handler(Looper.getMainLooper());
        handler.post(() -> {
            tts = new TextToSpeech(getContext(), this);
            tts.setOnUtteranceProgressListener(
                new UtteranceProgressListener() {
                    @Override
                    public void onStart(String utteranceId) {}

                    @Override
                    public void onDone(String utteranceId) {
                        Handler playbackHandler = new Handler(Looper.getMainLooper());
                        playbackHandler.post(() -> startPlayback());
                    }

                    @Override
                    public void onError(String utteranceId) {
                        notifyState("error", "语音合成失败");
                    }
                }
            );
        });
    }

    @Override
    public void onInit(int status) {
        initialized = status == TextToSpeech.SUCCESS;
        if (!initialized) {
            notifyState("error", "系统语音播报组件初始化失败");
        }
    }

    @PluginMethod
    public void available(PluginCall call) {
        JSObject result = new JSObject();
        result.put("available", initialized);
        call.resolve(result);
    }

    @PluginMethod
    public void speak(PluginCall call) {
        if (!initialized || tts == null) {
            call.reject("系统语音播报组件尚未就绪");
            return;
        }

        String text = call.getString("text", "").trim();
        if (text.isEmpty()) {
            call.reject("暂无可播报内容");
            return;
        }

        String lang = call.getString("lang", "zh-CN");
        float rate = call.getFloat("rate", 1.0f);
        float pitch = call.getFloat("pitch", 1.0f);
        currentVolume = call.getFloat("volume", 1.0f);

        stopInternal();

        Locale locale = Locale.forLanguageTag(lang);
        int languageStatus = tts.isLanguageAvailable(locale);
        if (
            languageStatus != TextToSpeech.LANG_AVAILABLE &&
            languageStatus != TextToSpeech.LANG_COUNTRY_AVAILABLE &&
            languageStatus != TextToSpeech.LANG_COUNTRY_VAR_AVAILABLE
        ) {
            call.reject("当前设备不支持中文语音播报");
            return;
        }

        tts.setLanguage(locale);
        tts.setSpeechRate(rate);
        tts.setPitch(pitch);

        try {
            currentAudioFile = File.createTempFile("tts_", ".wav", getContext().getCacheDir());
            String utteranceId = UUID.randomUUID().toString();
            Bundle params = new Bundle();
            params.putString(TextToSpeech.Engine.KEY_PARAM_UTTERANCE_ID, utteranceId);
            int result = tts.synthesizeToFile(text, params, currentAudioFile, utteranceId);
            if (result == TextToSpeech.ERROR) {
                call.reject("语音合成请求失败");
                return;
            }
            paused = false;
            notifyState("preparing", "");
            call.resolve();
        } catch (Exception ex) {
            call.reject(ex.getLocalizedMessage());
        }
    }

    @PluginMethod
    public void pause(PluginCall call) {
        if (mediaPlayer == null || !mediaPlayer.isPlaying()) {
            call.reject("当前没有正在播报的内容");
            return;
        }
        mediaPlayer.pause();
        paused = true;
        notifyState("paused", "");
        call.resolve();
    }

    @PluginMethod
    public void resume(PluginCall call) {
        if (mediaPlayer == null || !paused) {
            call.reject("当前没有可继续的播报");
            return;
        }
        mediaPlayer.start();
        paused = false;
        notifyState("playing", "");
        call.resolve();
    }

    @PluginMethod
    public void stop(PluginCall call) {
        stopInternal();
        call.resolve();
    }

    private void startPlayback() {
        if (currentAudioFile == null || !currentAudioFile.exists()) {
            notifyState("error", "语音音频文件不存在");
            return;
        }

        releasePlayerOnly();

        try {
            mediaPlayer = new MediaPlayer();
            mediaPlayer.setDataSource(currentAudioFile.getAbsolutePath());
            mediaPlayer.setVolume(currentVolume, currentVolume);
            mediaPlayer.setOnCompletionListener(mp -> {
                paused = false;
                notifyState("completed", "");
                releasePlayerOnly();
                deleteCurrentAudioFile();
            });
            mediaPlayer.prepare();
            mediaPlayer.start();
            paused = false;
            notifyState("playing", "");
        } catch (Exception ex) {
            notifyState("error", ex.getLocalizedMessage());
            releasePlayerOnly();
            deleteCurrentAudioFile();
        }
    }

    private void stopInternal() {
        if (tts != null) {
            try {
                tts.stop();
            } catch (Exception ignored) {}
        }
        paused = false;
        releasePlayerOnly();
        deleteCurrentAudioFile();
        notifyState("stopped", "");
    }

    private void releasePlayerOnly() {
        if (mediaPlayer == null) {
            return;
        }
        try {
            if (mediaPlayer.isPlaying()) {
                mediaPlayer.stop();
            }
        } catch (Exception ignored) {}
        mediaPlayer.release();
        mediaPlayer = null;
    }

    private void deleteCurrentAudioFile() {
        if (currentAudioFile != null && currentAudioFile.exists()) {
            //noinspection ResultOfMethodCallIgnored
            currentAudioFile.delete();
        }
        currentAudioFile = null;
    }

    private void notifyState(String state, String message) {
        JSObject ret = new JSObject();
        ret.put("state", state);
        ret.put("message", message);
        notifyListeners("playbackState", ret);
    }

    @Override
    protected void handleOnDestroy() {
        stopInternal();
        if (tts != null) {
            tts.shutdown();
            tts = null;
        }
        super.handleOnDestroy();
    }
}
