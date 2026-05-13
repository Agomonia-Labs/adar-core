/**
 * ui/src/hooks/useSpeech.js
 *
 * Speech-to-text hook using:
 *   1. Web Speech API (primary — free, works in Chrome)
 *   2. Google Cloud STT via /api/stt (fallback — better Bengali accuracy)
 *
 * Usage:
 *   const { listening, supported, startListening, stopListening } = useSpeech({
 *     lang:      'bn-IN',
 *     onResult:  (text) => setInput(prev => prev + text),
 *     onError:   (err)  => console.warn(err),
 *   })
 */

import { useState, useRef, useCallback, useEffect } from 'react'

const API_URL = import.meta.env.VITE_API_URL || ''

// ── Web Speech API check ──────────────────────────────────────────────────────
const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition || null

const WEB_SPEECH_SUPPORTED = Boolean(SpeechRecognition)
const CLOUD_STT_SUPPORTED  = Boolean(API_URL)

// Mic is available if EITHER engine works
// Firefox/iOS → Cloud STT; Chrome/Edge → Web Speech

export function useSpeech({ lang = 'bn-IN', onResult, onError } = {}) {
  const [listening, setListening]   = useState(false)
  const recognitionRef = useRef(null)
  const mediaRecRef    = useRef(null)
  const chunksRef      = useRef([])

  const supported = WEB_SPEECH_SUPPORTED || CLOUD_STT_SUPPORTED

  // ── Web Speech API ──────────────────────────────────────────────────────────
  const startWebSpeech = useCallback(() => {
    const rec = new SpeechRecognition()
    rec.lang          = lang
    rec.interimResults = true
    rec.maxAlternatives = 1
    rec.continuous    = false

    let finalTranscript = ''

    rec.onstart  = () => setListening(true)
    rec.onend    = () => {
      setListening(false)
      if (finalTranscript.trim()) onResult?.(finalTranscript.trim())
    }
    rec.onerror  = (e) => {
      setListening(false)
      onError?.(e.error)
      // Fallback to Cloud STT if Web Speech fails with 'not-allowed' or 'service-not-allowed'
      if (e.error === 'service-not-allowed' || e.error === 'not-allowed') {
        onError?.('মাইক্রোফোন অনুমতি প্রয়োজন। ব্রাউজার সেটিংসে মাইক্রোফোন চালু করুন।')
      }
    }
    rec.onresult = (e) => {
      finalTranscript = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) {
          finalTranscript += e.results[i][0].transcript
        }
      }
    }

    recognitionRef.current = rec
    rec.start()
  }, [lang, onResult, onError])

  const stopWebSpeech = useCallback(() => {
    recognitionRef.current?.stop()
    setListening(false)
  }, [])

  // ── Google Cloud STT via /api/stt ─────────────────────────────────────────
  const startCloudSTT = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })

      // Pick a MIME type — Safari only supports audio/mp4
      // Chrome/Firefox prefer webm/ogg for better STT compatibility
      const mimeType = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/ogg;codecs=opus',
        'audio/ogg',
        'audio/mp4',             // Safari fallback
      ].find(m => MediaRecorder.isTypeSupported(m)) || ''
      console.log('Recording MIME:', mimeType || 'browser default')

      const mr = new MediaRecorder(stream, mimeType ? { mimeType } : {})
      chunksRef.current = []

      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      mr.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        setListening(false)
        const actualMime = mimeType || 'audio/webm'
        const blob   = new Blob(chunksRef.current, { type: actualMime })
        const reader = new FileReader()
        reader.onloadend = async () => {
          const b64 = reader.result.split(',')[1]
          try {
            const token = localStorage.getItem('adar_token') || ''
            const resp  = await fetch(`${API_URL}/api/stt`, {
              method: 'POST',
              headers: {
                'Content-Type':  'application/json',
                'Authorization': `Bearer ${token}`,
              },
              body: JSON.stringify({ audio: b64, lang, mime: actualMime }),
            })
            if (!resp.ok) {
              const err = await resp.text()
              console.error('STT API error:', resp.status, err)
              onError?.('ভয়েস সার্ভার এরর: ' + resp.status)
              return
            }
            const data = await resp.json()
            console.log('STT response:', data)
            if (data.text) onResult?.(data.text)
            else onError?.('কথা বোঝা যায়নি, আবার চেষ্টা করুন।')
          } catch (e) {
            console.error('STT fetch error:', e)
            onError?.('সংযোগ সমস্যা: ' + e.message)
          }
        }
        reader.readAsDataURL(blob)
      }

      mediaRecRef.current = mr
      mr.start()
      setListening(true)
    } catch (e) {
      onError?.('মাইক্রোফোন চালু করা যায়নি: ' + e.message)
    }
  }, [lang, onResult, onError])

  const stopCloudSTT = useCallback(() => {
    mediaRecRef.current?.stop()
  }, [])

  // ── Public API ────────────────────────────────────────────────────────────
  const startListening = useCallback(() => {
    if (WEB_SPEECH_SUPPORTED) startWebSpeech()
    else if (CLOUD_STT_SUPPORTED) startCloudSTT()
  }, [startWebSpeech, startCloudSTT])

  const stopListening = useCallback(() => {
    if (WEB_SPEECH_SUPPORTED) stopWebSpeech()
    else stopCloudSTT()
  }, [stopWebSpeech, stopCloudSTT])

  // Cleanup on unmount
  useEffect(() => () => {
    recognitionRef.current?.abort()
    mediaRecRef.current?.stop()
  }, [])

  return { listening, supported, startListening, stopListening }
}