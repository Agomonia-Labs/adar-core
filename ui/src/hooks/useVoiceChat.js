// useVoiceChat.js
// Drop-in React hook for ADAR Geetabitan — Bangla voice in, Bangla voice out
// Usage: import useVoiceChat from './useVoiceChat';

import { useState, useCallback, useRef, useEffect } from 'react';

/**
 * Picks the best available Bangla TTS voice.
 * Priority: bn-BD > bn-IN > bn > fallback to first available.
 */
function pickBanglaVoice() {
  const voices = window.speechSynthesis.getVoices();
  const preferred = [
    v => v.lang === 'bn-BD',
    v => v.lang === 'bn-IN',
    v => v.lang.startsWith('bn'),
  ];
  for (const test of preferred) {
    const found = voices.find(test);
    if (found) return found;
  }
  // Graceful fallback: use whatever is available
  return voices[0] || null;
}

/**
 * useVoiceChat
 *
 * @param {Function} onTranscript  - called with the recognised Bangla text;
 *                                   should return a Promise<string> of the AI reply.
 * @param {Object}   options
 *   @param {string}  options.lang          - STT lang (default 'bn-BD')
 *   @param {number}  options.ttsRate       - speech rate 0.1–2 (default 0.9)
 *   @param {number}  options.ttsPitch      - pitch 0–2 (default 1)
 *   @param {boolean} options.autoSpeak     - auto-speak AI reply (default true)
 */
export function useVoiceChat(onTranscript, options = {}) {
  const {
    lang = 'bn-BD',
    ttsRate = 0.9,
    ttsPitch = 1,
    autoSpeak = true,
  } = options;

  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [error, setError] = useState(null);

  const recognitionRef = useRef(null);
  const utteranceRef = useRef(null);

  // ── Initialise SpeechRecognition ────────────────────────────────────────────
  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setError('এই ব্রাউজারে ভয়েস ইনপুট সাপোর্ট নেই।');
      return;
    }
    const rec = new SR();
    rec.lang = lang;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.continuous = false;

    rec.onresult = async (event) => {
      const text = event.results[0][0].transcript;
      setTranscript(text);
      setIsListening(false);
      setError(null);

      if (onTranscript) {
        try {
          const reply = await onTranscript(text);
          if (autoSpeak && reply) {
            speakBangla(reply);
          }
        } catch (err) {
          setError('উত্তর পেতে সমস্যা হয়েছে।');
        }
      }
    };

    rec.onerror = (e) => {
      setIsListening(false);
      if (e.error === 'no-speech') {
        setError('কথা শোনা যায়নি, আবার চেষ্টা করুন।');
      } else if (e.error === 'not-allowed') {
        setError('মাইক্রোফোন অ্যাক্সেস দিন।');
      } else {
        setError(`ভয়েস এরর: ${e.error}`);
      }
    };

    rec.onend = () => setIsListening(false);

    recognitionRef.current = rec;
  }, [lang, autoSpeak, onTranscript]);

  // ── Start listening ─────────────────────────────────────────────────────────
  const startListening = useCallback(() => {
    if (!recognitionRef.current) return;
    setError(null);
    setTranscript('');
    // Stop any ongoing speech before listening
    window.speechSynthesis.cancel();
    setIsSpeaking(false);
    recognitionRef.current.start();
    setIsListening(true);
  }, []);

  // ── Stop listening ──────────────────────────────────────────────────────────
  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    setIsListening(false);
  }, []);

  // ── Speak text in Bangla ────────────────────────────────────────────────────
  const speakBangla = useCallback((text) => {
    if (!text) return;
    window.speechSynthesis.cancel();

    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = lang;
    utter.rate = ttsRate;
    utter.pitch = ttsPitch;

    // Voices load asynchronously; try to pick Bangla voice
    const setVoiceAndSpeak = () => {
      const voice = pickBanglaVoice();
      if (voice) utter.voice = voice;
      utter.onstart = () => setIsSpeaking(true);
      utter.onend = () => setIsSpeaking(false);
      utter.onerror = () => setIsSpeaking(false);
      utteranceRef.current = utter;
      window.speechSynthesis.speak(utter);
    };

    if (window.speechSynthesis.getVoices().length > 0) {
      setVoiceAndSpeak();
    } else {
      // Voices not loaded yet (first call)
      window.speechSynthesis.onvoiceschanged = () => {
        setVoiceAndSpeak();
        window.speechSynthesis.onvoiceschanged = null;
      };
    }
  }, [lang, ttsRate, ttsPitch]);

  // ── Stop speaking ────────────────────────────────────────────────────────────
  const stopSpeaking = useCallback(() => {
    window.speechSynthesis.cancel();
    setIsSpeaking(false);
  }, []);

  return {
    isListening,
    isSpeaking,
    transcript,
    error,
    startListening,
    stopListening,
    speakBangla,
    stopSpeaking,
  };
}