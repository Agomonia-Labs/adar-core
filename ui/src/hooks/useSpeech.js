// hooks/useSpeech.js
// STT (speech-to-text) + TTS (text-to-speech) in Bangla
// Used by ChatTab in App.jsx

import { useState, useRef, useCallback, useEffect } from 'react'

// ── Pick the best available Bangla TTS voice ─────────────────────────────────
function pickBanglaVoice() {
  const voices = window.speechSynthesis?.getVoices() || []
  // Priority: exact bn-BD → bn-IN → any bn → fallback to first voice
  return (
    voices.find(v => v.lang === 'bn-BD') ||
    voices.find(v => v.lang === 'bn-IN') ||
    voices.find(v => v.lang.startsWith('bn')) ||
    voices[0] ||
    null
  )
}

/**
 * useSpeech
 *
 * Provides:
 *   listening      — bool, true while mic is active
 *   isSpeaking     — bool, true while TTS is playing
 *   supported      — bool, browser supports STT
 *   startListening — fn()
 *   stopListening  — fn()
 *   speakBangla    — fn(text: string) — speaks text in Bangla voice
 *   stopSpeaking   — fn()
 *
 * Options:
 *   lang      — STT language (default 'bn-BD')
 *   onResult  — fn(transcript: string) called when speech recognised
 *   onError   — fn(errorMessage: string)
 */
export function useSpeech({ lang = 'bn-BD', onResult, onError } = {}) {
  const [listening,  setListening]  = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const recognitionRef = useRef(null)
  const supported = !!(window.SpeechRecognition || window.webkitSpeechRecognition)

  // ── Initialise SpeechRecognition ──────────────────────────────────────────
  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return

    const rec = new SR()
    rec.lang            = lang
    rec.interimResults  = false
    rec.maxAlternatives = 1
    rec.continuous      = false

    rec.onresult = (event) => {
      const transcript = event.results[0][0].transcript
      setListening(false)
      if (transcript.trim()) onResult?.(transcript.trim())
    }

    rec.onerror = (e) => {
      setListening(false)
      const msgs = {
        'no-speech':   'কথা শোনা যায়নি — আবার চেষ্টা করুন।',
        'not-allowed': 'মাইক্রোফোন অ্যাক্সেস দিন।',
        'network':     'নেটওয়ার্ক সমস্যা।',
      }
      onError?.(msgs[e.error] || `ভয়েস এরর: ${e.error}`)
    }

    rec.onend = () => setListening(false)

    recognitionRef.current = rec
  }, [lang, onResult, onError])

  // ── STT controls ──────────────────────────────────────────────────────────
  const startListening = useCallback(() => {
    if (!recognitionRef.current || listening) return
    // Stop any active speech before listening
    window.speechSynthesis?.cancel()
    setIsSpeaking(false)
    recognitionRef.current.start()
    setListening(true)
  }, [listening])

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop()
    setListening(false)
  }, [])

  // ── TTS: speak reply in Bangla ────────────────────────────────────────────
  const speakBangla = useCallback((text) => {
    if (!text || !window.speechSynthesis) return
    window.speechSynthesis.cancel()

    // Strip markdown symbols so they aren't read aloud
    const clean = text
      .replace(/#{1,6}\s/g, '')         // headings
      .replace(/\*\*(.+?)\*\*/g, '$1') // bold
      .replace(/\*(.+?)\*/g, '$1')     // italic
      .replace(/`(.+?)`/g, '$1')       // inline code
      .replace(/\|.+\|/g, '')          // table rows
      .replace(/[-*_]{3,}/g, '')       // hr
      .replace(/\[(.+?)\]\(.+?\)/g, '$1') // links
      .replace(/\n{2,}/g, '. ')        // paragraph breaks → pause
      .trim()

    const utter = new SpeechSynthesisUtterance(clean)
    utter.lang  = 'bn-BD'
    utter.rate  = 0.88   // slightly slower for clarity
    utter.pitch = 1.0

    const doSpeak = () => {
      const voice = pickBanglaVoice()
      if (voice) utter.voice = voice
      utter.onstart  = () => setIsSpeaking(true)
      utter.onend    = () => setIsSpeaking(false)
      utter.onerror  = () => setIsSpeaking(false)
      window.speechSynthesis.speak(utter)
    }

    // Voices may not be loaded yet on first call
    if (window.speechSynthesis.getVoices().length > 0) {
      doSpeak()
    } else {
      window.speechSynthesis.onvoiceschanged = () => {
        doSpeak()
        window.speechSynthesis.onvoiceschanged = null
      }
    }
  }, [])

  const stopSpeaking = useCallback(() => {
    window.speechSynthesis?.cancel()
    setIsSpeaking(false)
  }, [])

  return { listening, isSpeaking, supported, startListening, stopListening, speakBangla, stopSpeaking }
}