import { useState, useEffect } from 'react'
import type { OcrSensitivity } from '@/types'
import { get, put } from '@/api/client'

interface SystemSettingsResponse {
  success: boolean
  ocr_sensitivity: OcrSensitivity
  ocr_confidence_threshold?: number
  marking_confidence_threshold?: number
  cache_enabled: boolean
}

function Settings() {
  // State management
  const [ocrSensitivity, setOcrSensitivity] = useState<OcrSensitivity>('medium')
  const [ocrThreshold, setOcrThreshold] = useState<number>(75)
  const [markingThreshold, setMarkingThreshold] = useState<number>(70)
  const [showClearCacheConfirm, setShowClearCacheConfirm] = useState(false)
  const [cacheCleared, setCacheCleared] = useState(false)
  const [settingsSaved, setSettingsSaved] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  // Load settings on mount from backend and localStorage
  useEffect(() => {
    const loadSettings = async () => {
      try {
        const data = await get<SystemSettingsResponse>('/settings')
        if (data.ocr_sensitivity) {
          setOcrSensitivity(data.ocr_sensitivity)
          localStorage.setItem('ocr_sensitivity', data.ocr_sensitivity)
        }
        if (data.ocr_confidence_threshold !== undefined) {
          setOcrThreshold(Math.round(data.ocr_confidence_threshold * 100))
        }
        if (data.marking_confidence_threshold !== undefined) {
          setMarkingThreshold(Math.round(data.marking_confidence_threshold * 100))
        }
      } catch {
        // Fallback to localStorage
        const savedSensitivity = localStorage.getItem('ocr_sensitivity') as OcrSensitivity
        if (savedSensitivity) setOcrSensitivity(savedSensitivity)
      }
    }

    loadSettings()
  }, [])

  // Save settings to backend and localStorage
  const saveSettings = async (sens: OcrSensitivity, ocrThresh: number, markThresh: number) => {
    setIsSaving(true)
    try {
      await put<SystemSettingsResponse>('/settings', {
        ocr_sensitivity: sens,
        ocr_confidence_threshold: ocrThresh / 100,
        marking_confidence_threshold: markThresh / 100,
      })
      localStorage.setItem('ocr_sensitivity', sens)
      setSettingsSaved(true)
      setTimeout(() => setSettingsSaved(false), 3000)
    } catch (err) {
      console.error('Failed to save settings to server:', err)
    } finally {
      setIsSaving(false)
    }
  }

  // Handle OCR sensitivity change
  const handleSensitivityChange = (value: OcrSensitivity) => {
    setOcrSensitivity(value)
    saveSettings(value, ocrThreshold, markingThreshold)
  }

  // Handle clear cache action
  const handleClearCache = () => {
    const sensitivityBackup = localStorage.getItem('ocr_sensitivity')
    localStorage.clear()
    if (sensitivityBackup) {
      localStorage.setItem('ocr_sensitivity', sensitivityBackup)
    }

    setCacheCleared(true)
    setShowClearCacheConfirm(false)
    setTimeout(() => setCacheCleared(false), 5000)
  }

  const getSensitivityDescription = (level: OcrSensitivity): string => {
    const descriptions = {
      low: 'Faster processing, may miss some characters. Best for clean, printed text.',
      medium: 'Balanced accuracy and speed. Recommended for most use cases.',
      high: 'Maximum accuracy, slower processing. Best for handwritten or poor quality scans.',
    }
    return descriptions[level]
  }

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-800 mb-2">Settings</h1>
        <p className="text-slate-600">
          Configure global application preferences, AI confidence verification, and data management
        </p>
      </div>

      {/* Settings Saved Notification */}
      {settingsSaved && (
        <div className="bg-green-50 border-2 border-green-200 rounded-lg p-4 mb-6">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-green-600" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
            <p className="text-sm font-semibold text-green-800">Settings saved successfully!</p>
          </div>
        </div>
      )}

      {/* Stage 4 Confidence-Based Verification Thresholds Section */}
      <div className="bg-white border-2 border-slate-200 rounded-lg p-6 mb-6">
        <div className="flex items-start gap-3 mb-6">
          <div className="p-2 bg-amber-100 text-amber-700 rounded-lg shrink-0 mt-0.5">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-bold text-slate-800">Stage 4 Confidence-Based Verification</h2>
              <span className="text-[11px] font-semibold bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full border border-amber-300">
                Weak-Link Rule
              </span>
            </div>
            <p className="text-sm text-slate-600 mt-1">
              Scripts are flagged for Educator Review only when AI certainty falls below these sensitivity thresholds.
              Low marks alone will <strong>never</strong> flag an answer sheet.
            </p>
          </div>
        </div>

        <div className="space-y-6">
          {/* OCR Confidence Threshold Slider */}
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-5">
            <div className="flex justify-between items-center mb-2">
              <div>
                <label className="text-sm font-bold text-slate-800">
                  OCR / Handwriting Readability Threshold
                </label>
                <p className="text-xs text-slate-500 mt-0.5">
                  Flags scripts when handwriting legibility or transcription certainty is below this level.
                </p>
              </div>
              <span className="text-sm font-bold px-3 py-1 bg-white border border-slate-300 rounded-md text-blue-700 font-mono">
                {ocrThreshold}%
              </span>
            </div>

            <div className="flex items-center gap-4 mt-3">
              <span className="text-xs text-slate-400 font-semibold">50% (Permissive)</span>
              <input
                type="range"
                min="50"
                max="95"
                step="1"
                value={ocrThreshold}
                onChange={(e) => setOcrThreshold(Number(e.target.value))}
                onMouseUp={() => saveSettings(ocrSensitivity, ocrThreshold, markingThreshold)}
                className="flex-1 h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
              />
              <span className="text-xs text-slate-400 font-semibold">95% (Strict)</span>
            </div>
          </div>

          {/* Marking Confidence Threshold Slider */}
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-5">
            <div className="flex justify-between items-center mb-2">
              <div>
                <label className="text-sm font-bold text-slate-800">
                  Rubric Grading Certainty Threshold
                </label>
                <p className="text-xs text-slate-500 mt-0.5">
                  Flags scripts if the AI's grading certainty on <strong>any individual rubric component</strong> falls below this level.
                </p>
              </div>
              <span className="text-sm font-bold px-3 py-1 bg-white border border-slate-300 rounded-md text-amber-700 font-mono">
                {markingThreshold}%
              </span>
            </div>

            <div className="flex items-center gap-4 mt-3">
              <span className="text-xs text-slate-400 font-semibold">50% (Permissive)</span>
              <input
                type="range"
                min="50"
                max="95"
                step="1"
                value={markingThreshold}
                onChange={(e) => setMarkingThreshold(Number(e.target.value))}
                onMouseUp={() => saveSettings(ocrSensitivity, ocrThreshold, markingThreshold)}
                className="flex-1 h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-amber-600"
              />
              <span className="text-xs text-slate-400 font-semibold">95% (Strict)</span>
            </div>
          </div>

          <div className="flex justify-end">
            <button
              onClick={() => saveSettings(ocrSensitivity, ocrThreshold, markingThreshold)}
              disabled={isSaving}
              className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm rounded-lg transition-colors shadow-sm disabled:opacity-50"
            >
              {isSaving ? 'Saving...' : 'Apply Thresholds ✓'}
            </button>
          </div>
        </div>
      </div>

      {/* OCR Settings Section */}
      <div className="bg-white border-2 border-slate-200 rounded-lg p-6 mb-6">
        <div className="flex items-start gap-3 mb-6">
          <svg className="w-6 h-6 text-blue-600 shrink-0 mt-1" fill="currentColor" viewBox="0 0 20 20">
            <path d="M13 7H7v6h6V7z" />
            <path fillRule="evenodd" d="M7 2a1 1 0 012 0v1h2V2a1 1 0 112 0v1h2a2 2 0 012 2v2h1a1 1 0 110 2h-1v2h1a1 1 0 110 2h-1v2a2 2 0 01-2 2h-2v1a1 1 0 11-2 0v-1H9v1a1 1 0 11-2 0v-1H5a2 2 0 01-2-2v-2H2a1 1 0 110-2h1V9H2a1 1 0 010-2h1V5a2 2 0 012-2h2V2zM5 5h10v10H5V5z" clipRule="evenodd" />
          </svg>
          <div className="flex-1">
            <h2 className="text-xl font-bold text-slate-800 mb-2">OCR Processing Sensitivity</h2>
            <p className="text-sm text-slate-600">
              Configure optical character recognition preprocessing mode for answer sheet scanning
            </p>
          </div>
        </div>

        <div>
          <label htmlFor="ocr-sensitivity" className="block text-sm font-semibold text-slate-700 mb-3">
            Preprocessing Mode
          </label>

          <select
            id="ocr-sensitivity"
            value={ocrSensitivity}
            onChange={(e) => handleSensitivityChange(e.target.value as OcrSensitivity)}
            className="w-full md:w-1/2 px-4 py-3 border-2 border-slate-300 rounded-lg focus:outline-none focus:border-blue-600 transition-colors text-slate-800 font-medium cursor-pointer"
          >
            <option value="low">Low - Fast Processing</option>
            <option value="medium">Medium - Balanced (Recommended)</option>
            <option value="high">High - Maximum Accuracy</option>
          </select>

          <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div className="flex gap-3">
              <svg className="w-5 h-5 text-blue-600 shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
              <div className="text-sm text-blue-800">
                <p className="font-semibold mb-1">
                  {ocrSensitivity === 'low' ? 'Low Sensitivity' :
                    ocrSensitivity === 'medium' ? 'Medium Sensitivity' :
                      'High Sensitivity'}
                </p>
                <p>{getSensitivityDescription(ocrSensitivity)}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Data Management Section */}
      <div className="bg-white border-2 border-slate-200 rounded-lg p-6 mb-6">
        <div className="flex items-start gap-3 mb-6">
          <svg className="w-6 h-6 text-slate-700 shrink-0 mt-1" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M3 3a1 1 0 000 2v8a2 2 0 002 2h2.586l-1.293 1.293a1 1 0 101.414 1.414L10 15.414l2.293 2.293a1 1 0 001.414-1.414L12.414 15H15a2 2 0 002-2V5a1 1 0 100-2H3zm11.707 4.707a1 1 0 00-1.414-1.414L10 9.586 8.707 8.293a1 1 0 00-1.414 0l-2 2a1 1 0 101.414 1.414L8 10.414l1.293 1.293a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
          <div className="flex-1">
            <h2 className="text-xl font-bold text-slate-800 mb-2">Data Management</h2>
            <p className="text-sm text-slate-600">
              Manage cached evaluation data and temporary files
            </p>
          </div>
        </div>

        <div>
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <h3 className="font-bold text-slate-800 mb-2">Clear Application Cache</h3>
                <p className="text-sm text-slate-600 mb-3">
                  Remove all cached evaluation data, uploaded files, and temporary processing results.
                  This action will not affect your saved settings.
                </p>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                  </svg>
                  <span>Your OCR and confidence settings will be preserved</span>
                </div>
              </div>

              <button
                onClick={() => setShowClearCacheConfirm(true)}
                className="shrink-0 px-6 py-2 bg-red-600 hover:bg-red-700 text-white font-semibold rounded-lg transition-colors duration-200"
              >
                Clear Cache
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Cache Cleared Success Message */}
      {cacheCleared && (
        <div className="bg-green-50 border-2 border-green-200 rounded-lg p-6 mb-6">
          <div className="flex items-start gap-3">
            <svg className="w-6 h-6 text-green-600 shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
            <div className="flex-1">
              <h3 className="text-lg font-bold text-green-800 mb-2">Cache Cleared Successfully!</h3>
              <p className="text-sm text-green-700">
                All temporary data has been removed. Your application is now running with a clean slate.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Confirmation Modal */}
      {showClearCacheConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-start gap-3 mb-4">
              <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center shrink-0">
                <svg className="w-6 h-6 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-bold text-slate-800 mb-2">Clear Application Cache?</h3>
                <p className="text-sm text-slate-600 mb-4">
                  This will permanently remove all cached evaluation data, uploaded files, and temporary results.
                  This action cannot be undone.
                </p>
              </div>
            </div>

            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowClearCacheConfirm(false)}
                className="px-5 py-2 border-2 border-slate-300 text-slate-700 font-semibold rounded-lg hover:bg-slate-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleClearCache}
                className="px-5 py-2 bg-red-600 hover:bg-red-700 text-white font-semibold rounded-lg transition-colors"
              >
                Clear Cache
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Settings
