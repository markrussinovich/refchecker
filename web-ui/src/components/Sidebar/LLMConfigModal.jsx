import { useState, useEffect, useMemo } from 'react'
import Modal from '../common/Modal'
import Button from '../common/Button'
import { useConfigStore } from '../../stores/useConfigStore'
import { useKeyStore } from '../../stores/useKeyStore'
import { useAuthStore } from '../../stores/useAuthStore'
import { validateLLMConfig, listLLMModels } from '../../utils/api'
import { logger } from '../../utils/logger'

// Keep in sync with src/refchecker/config/settings.py DEFAULT_EXTRACTION_MODELS
const PROVIDERS = [
  { id: 'openai', name: 'OpenAI', defaultModel: 'gpt-4.1', requiresKey: true, hallucinationCapable: true },
  { id: 'anthropic', name: 'Anthropic', defaultModel: 'claude-sonnet-4-6', requiresKey: true, hallucinationCapable: true },
  { id: 'google', name: 'Google', defaultModel: 'gemini-3.1-flash-lite-preview', requiresKey: true, hallucinationCapable: true },
  { id: 'azure', name: 'Azure OpenAI', defaultModel: 'gpt-4.1', requiresKey: true, requiresEndpoint: true, hallucinationCapable: true },
  { id: 'vllm', name: 'vLLM (Local)', defaultModel: 'meta-llama/Llama-3.1-8B-Instruct', requiresKey: false, requiresEndpoint: true, hallucinationCapable: false },
]

/**
 * Modal for adding/editing LLM configurations
 */
export default function LLMConfigModal({ isOpen, onClose, editConfig = null, prefillConfig = null, selectionMode = 'extraction' }) {
  const { addConfig, updateConfig, configs, selectHallucinationConfig, selectConfig } = useConfigStore()
  const multiuser = useAuthStore(state => state.multiuser)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [error, setError] = useState(null)

  const [formData, setFormData] = useState({
    provider: 'anthropic',
    model: '',
    api_key: '',
    endpoint: '',
  })

  // Live model lookup state
  const [modelOptions, setModelOptions] = useState([]) // string[]
  const [modelSource, setModelSource] = useState(null) // 'live' | 'fallback' | null
  const [modelFetching, setModelFetching] = useState(false)
  const [modelError, setModelError] = useState(null)

  // Test-connection state
  const [testResult, setTestResult] = useState(null) // { ok, message }
  const [testing, setTesting] = useState(false)

  // Reset form when modal opens/closes or editConfig changes
  useEffect(() => {
    if (isOpen) {
      // When creating a new config with a prefillConfig (keyless config for same provider),
      // use its model/provider so the user just needs to add the API key
      const source = editConfig || prefillConfig
      const defaultProvider = source?.provider || 'anthropic'
      setFormData({
        provider: defaultProvider,
        model: source?.model || '',
        api_key: '',
        endpoint: source?.endpoint || '',
      })
      setError(null)
    }
  }, [isOpen, editConfig, prefillConfig])

  const availableProviders = useMemo(
    () => (multiuser ? PROVIDERS.filter(p => p.id !== 'vllm') : PROVIDERS),
    [multiuser],
  )
  const selectedProvider = availableProviders.find(p => p.id === formData.provider)
  const existingProviderConfig = configs.find(config => (
    config.provider === formData.provider &&
    config.id !== editConfig?.id &&
    (config.has_key || useKeyStore.getState().hasKey(config.provider) || useKeyStore.getState().hasKey(`llm:${config.id}`))
  ))
  const reusableProviderKey = (
    useKeyStore.getState().getKey(formData.provider) ||
    (existingProviderConfig ? useKeyStore.getState().getKey(`llm:${existingProviderConfig.id}`) : null)
  )
  const hasReusableProviderKey = !!existingProviderConfig || !!reusableProviderKey
  const hasServerEnvironmentKey = existingProviderConfig?.key_source === 'environment' || existingProviderConfig?.env_key_available

  useEffect(() => {
    if (!multiuser) return
    if (formData.provider === 'vllm') {
      const fallbackProvider = availableProviders[0]
      setFormData(prev => ({
        ...prev,
        provider: fallbackProvider?.id || 'anthropic',
        model: '',
        endpoint: '',
      }))
    }
  }, [availableProviders, formData.provider, multiuser])

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
    setError(null)
  }

  const handleProviderChange = (e) => {
    const provider = e.target.value
    setFormData(prev => ({
      ...prev,
      provider,
      model: '', // Reset model when provider changes
      endpoint: provider === 'vllm' ? 'http://localhost:8000' : prev.endpoint,
    }))
    setError(null)
    setModelOptions([])
    setModelSource(null)
    setModelError(null)
    setTestResult(null)
  }

  // Live model lookup — falls back to the curated static list when the
  // provider's /models endpoint isn't available or returns an error.
  const handleFetchModels = async () => {
    setModelError(null)
    setModelFetching(true)
    try {
      const effectiveKey = formData.api_key.trim() || reusableProviderKey || undefined
      const res = await listLLMModels(
        formData.provider,
        effectiveKey,
        formData.endpoint.trim() || undefined,
      )
      setModelOptions(res.data.models || [])
      setModelSource(res.data.source || 'fallback')
      if (res.data.error) setModelError(res.data.error)
    } catch (err) {
      setModelError(err.response?.data?.detail || err.message || 'Lookup failed')
      setModelOptions([])
      setModelSource(null)
    } finally {
      setModelFetching(false)
    }
  }

  // "Test connection" — runs the same validation the Save flow does, but
  // without persisting. Lets users iterate on model+key before committing.
  const handleTestConnection = async () => {
    setTestResult(null)
    if (selectedProvider?.requiresKey && !formData.api_key.trim() && !hasReusableProviderKey) {
      setTestResult({ ok: false, message: 'Enter an API key first.' })
      return
    }
    if (selectedProvider?.requiresEndpoint && !formData.endpoint.trim()) {
      setTestResult({ ok: false, message: 'Endpoint URL is required.' })
      return
    }
    setTesting(true)
    try {
      const payload = {
        provider: formData.provider,
        model: formData.model.trim() || selectedProvider?.defaultModel || null,
        api_key: formData.api_key.trim() || reusableProviderKey || undefined,
        endpoint: formData.endpoint.trim() || undefined,
      }
      const res = await validateLLMConfig(payload)
      if (res.data?.valid) {
        setTestResult({ ok: true, message: res.data.message || res.data.warning || 'Connection successful' })
      } else {
        setTestResult({ ok: false, message: res.data?.error || 'Validation failed' })
      }
    } catch (err) {
      let msg = err.response?.data?.detail
      if (Array.isArray(msg)) msg = msg.map(e => e.msg || JSON.stringify(e)).join(', ')
      else if (msg && typeof msg !== 'string') msg = msg.message || JSON.stringify(msg)
      setTestResult({ ok: false, message: msg || err.message || 'Test failed' })
    } finally {
      setTesting(false)
    }
  }

  const validate = () => {
    if (selectedProvider?.requiresKey && !editConfig && !formData.api_key.trim() && !hasReusableProviderKey) {
      setError('API key is required')
      return false
    }

    if (selectedProvider?.requiresEndpoint && !formData.endpoint.trim()) {
      setError('Endpoint URL is required')
      return false
    }

    return true
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    
    if (!validate()) return

    setIsSubmitting(true)
    setError(null)

    try {
      const effectiveModel = formData.model.trim() || selectedProvider?.defaultModel || null
      const configData = {
        // Name is no longer user-editable; use the model identifier so it
        // shows up consistently in selectors and history rows.
        name: effectiveModel || formData.provider,
        provider: formData.provider,
        model: effectiveModel,
        endpoint: formData.endpoint.trim() || null,
      }

      const effectiveApiKey = formData.api_key.trim() || reusableProviderKey

      // Only include API key if it was entered or is available from this browser cache.
      if (effectiveApiKey) {
        configData.api_key = effectiveApiKey
      }

      // Validate API connection before saving (only for new configs or when API key is provided)
      if (selectedProvider?.requiresKey && (effectiveApiKey || (!editConfig && !existingProviderConfig))) {
        setIsValidating(true)
        try {
          const validationData = {
            provider: configData.provider,
            model: configData.model,
            api_key: effectiveApiKey,
            endpoint: configData.endpoint,
          }
          logger.info('LLMConfigModal', 'Validating API connection...', { provider: configData.provider, model: configData.model })
          const response = await validateLLMConfig(validationData)
          if (!response.data.valid) {
            throw new Error(response.data.error || 'API validation failed')
          }
          if (response.data.warning) {
            logger.warn('LLMConfigModal', 'API validation warning', response.data.warning)
            // Don't setError here — the modal will close after save and
            // the warning would only flash briefly as a red error banner.
          }
          logger.info('LLMConfigModal', 'API validation successful')
        } catch (validationErr) {
          logger.error('LLMConfigModal', 'API validation failed', validationErr)
          // Handle various error response formats and sanitize output
          let errorMsg = 'Unknown error'
          const detail = validationErr.response?.data?.detail
          
          if (detail) {
            if (typeof detail === 'string') {
              errorMsg = detail
            } else if (Array.isArray(detail)) {
              // Pydantic validation errors - extract just the message
              const messages = detail.map(err => {
                const field = err.loc?.slice(1).join('.') || 'field'
                return `${field}: ${err.msg}`
              })
              errorMsg = messages.join(', ')
            } else if (detail.message) {
              errorMsg = detail.message
            } else {
              errorMsg = 'Validation failed'
            }
          } else if (validationErr.response?.data?.message) {
            errorMsg = validationErr.response.data.message
          } else if (typeof validationErr.message === 'string') {
            errorMsg = validationErr.message
          }
          
          // Remove any API key from error message for security
          errorMsg = errorMsg.replace(/sk-[a-zA-Z0-9-_]+/g, '[REDACTED]')
          errorMsg = errorMsg.replace(/"api_key":\s*"[^"]+"/g, '"api_key":"[REDACTED]"')
          
          setError(`API validation failed: ${errorMsg}`)
          setIsValidating(false)
          setIsSubmitting(false)
          return
        }
        setIsValidating(false)
      }

      let savedConfig = null
      if (editConfig) {
        savedConfig = await updateConfig(editConfig.id, configData)
        // Re-fetch to get updated has_key flags
        await useConfigStore.getState().fetchConfigs()
        logger.info('LLMConfigModal', 'Config updated')
      } else if (prefillConfig) {
        // Update the existing keyless config instead of creating a duplicate
        savedConfig = await updateConfig(prefillConfig.id, configData)
        // Re-fetch configs to get updated has_key flags from backend
        await useConfigStore.getState().fetchConfigs()
        if (selectionMode === 'hallucination') {
          selectHallucinationConfig(prefillConfig.id)
        } else {
          await selectConfig(prefillConfig.id)
        }
        logger.info('LLMConfigModal', 'Keyless config updated with key')
      } else {
        savedConfig = await addConfig(configData, { selectFor: selectionMode })
        logger.info('LLMConfigModal', 'Config created')
      }

      // Save the API key in memory for this tab so it's available for check submissions
      if (effectiveApiKey) {
        const configId = editConfig?.id || prefillConfig?.id || savedConfig?.id
        if (configId) {
          useKeyStore.getState().setKey(`llm:${configId}`, effectiveApiKey)
        }
        useKeyStore.getState().setKey(formData.provider, effectiveApiKey)
        logger.info('LLMConfigModal', 'API key saved to local key store', { provider: formData.provider })
      }

      onClose()
    } catch (err) {
      logger.error('LLMConfigModal', 'Failed to save config', err)
      setError(err.response?.data?.detail || err.message || 'Failed to save configuration')
    } finally {
      setIsSubmitting(false)
      setIsValidating(false)
    }
  }

  return (
    <Modal 
      isOpen={isOpen} 
      onClose={onClose} 
      title={editConfig ? 'Edit LLM Configuration' : 'Add LLM Configuration'}
      size="md"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Provider */}
        <div>
          <label 
            htmlFor="provider"
            className="block text-sm font-medium mb-1"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Provider
          </label>
          <select
            id="provider"
            name="provider"
            value={formData.provider}
            onChange={handleProviderChange}
            className="w-full px-3 py-2 rounded-lg border focus:outline-none focus:ring-2"
            style={{
              backgroundColor: 'var(--color-bg-secondary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          >
            {availableProviders.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <p
            className="mt-1 text-xs"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {selectedProvider?.hallucinationCapable
              ? 'Can be used for extraction and hallucination checks.'
              : 'Local vLLM is available for extraction only.'}
          </p>
        </div>

        {/* Model — combobox: live dropdown of available models + free text */}
        <div>
          <label
            htmlFor="model"
            className="block text-sm font-medium mb-1"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Model
            <span className="ml-1 font-normal" style={{ color: 'var(--color-text-muted)' }}>
              (optional)
            </span>
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              id="model"
              name="model"
              list="llm-model-options"
              autoComplete="off"
              value={formData.model}
              onChange={handleChange}
              placeholder={selectedProvider?.defaultModel || 'Default model'}
              className="flex-1 px-3 py-2 rounded-lg border focus:outline-none focus:ring-2"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
            />
            <button
              type="button"
              onClick={handleFetchModels}
              disabled={modelFetching}
              className="px-3 py-2 rounded-lg text-sm font-medium border"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)',
                opacity: modelFetching ? 0.6 : 1,
              }}
              title="Query the provider's /models endpoint with the current API key. Falls back to a curated list when the live lookup isn't supported."
            >
              {modelFetching ? 'Loading…' : 'Fetch'}
            </button>
          </div>
          <datalist id="llm-model-options">
            {modelOptions.map(m => <option key={m} value={m} />)}
          </datalist>
          <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>
            {modelSource === 'live'
              ? `Live list from provider (${modelOptions.length} models). You can also type any model id.`
              : modelSource === 'fallback'
                ? `Showing curated fallback list (${modelOptions.length} models). Type any model id, or click Fetch with a valid API key.`
                : `Default: ${selectedProvider?.defaultModel}. Type any model id, or click Fetch to query the provider with your API key.`}
          </p>
          {modelError && (
            <p className="mt-1 text-xs" style={{ color: 'var(--color-error, #ef4444)' }}>
              Lookup error: {modelError}
            </p>
          )}
        </div>

        {/* API Key */}
        {selectedProvider?.requiresKey && (
          <div>
            <label 
              htmlFor="api_key"
              className="block text-sm font-medium mb-1"
              style={{ color: 'var(--color-text-primary)' }}
            >
              API Key
              {editConfig && (
                <span 
                  className="ml-1 font-normal"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  (leave blank to keep existing)
                </span>
              )}
            </label>
            <input
              type="password"
              id="api_key"
              name="api_key"
              value={formData.api_key}
              onChange={handleChange}
              placeholder={editConfig ? '••••••••' : hasReusableProviderKey ? 'Reuse existing provider key' : 'Enter API key'}
              className="w-full px-3 py-2 rounded-lg border focus:outline-none focus:ring-2"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
            />
            <p 
              className="mt-1 text-xs"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {multiuser
                ? hasServerEnvironmentKey && !formData.api_key
                  ? 'Using the server environment key by default. Enter a key here to override it for this browser.'
                  : 'Retrieved from this encrypted browser cache for the local web interface and not stored in the local database or on the server.'
                : hasReusableProviderKey && !editConfig
                  ? hasServerEnvironmentKey
                    ? 'Defaults to the server environment key. Enter a key here to store a local encrypted override.'
                    : 'Defaults to the existing encrypted provider key in the local RefChecker database.'
                  : 'Stored encrypted in the local RefChecker database and never shown again.'}
            </p>
          </div>
        )}

        {/* Endpoint */}
        {selectedProvider?.requiresEndpoint && (
          <div>
            <label 
              htmlFor="endpoint"
              className="block text-sm font-medium mb-1"
              style={{ color: 'var(--color-text-primary)' }}
            >
              Endpoint URL
            </label>
            <input
              type="url"
              id="endpoint"
              name="endpoint"
              value={formData.endpoint}
              onChange={handleChange}
              placeholder={formData.provider === 'vllm' ? 'http://localhost:8000' : 'https://your-resource.openai.azure.com'}
              className="w-full px-3 py-2 rounded-lg border focus:outline-none focus:ring-2"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
            />
          </div>
        )}

        {/* Error message */}
        {error && (
          <div 
            className="p-3 rounded-lg text-sm break-words overflow-hidden"
            style={{
              backgroundColor: 'var(--color-error-bg)',
              color: 'var(--color-error)',
              maxHeight: '120px',
              overflowY: 'auto',
              wordBreak: 'break-word',
            }}
          >
            {error}
          </div>
        )}

        {/* Test result */}
        {testResult && (
          <div
            className="p-3 rounded-lg border text-sm"
            style={{
              backgroundColor: testResult.ok ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
              borderColor: testResult.ok ? 'var(--color-success, #22c55e)' : 'var(--color-error, #ef4444)',
              color: testResult.ok ? 'var(--color-success, #22c55e)' : 'var(--color-error, #ef4444)',
              wordBreak: 'break-word',
            }}
          >
            {testResult.ok ? '✓ ' : '✗ '}{testResult.message}
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-col gap-3 pt-2">
          <Button
            type="button"
            variant="secondary"
            onClick={handleTestConnection}
            disabled={isSubmitting || isValidating || testing}
            loading={testing}
            className="w-full"
            title="Run a small live call to verify the API key + model before saving"
          >
            {testing ? 'Testing…' : 'Test connection'}
          </Button>
          <div className="flex justify-end gap-3">
            <Button
              type="button"
              variant="secondary"
              onClick={onClose}
              disabled={isSubmitting || isValidating}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              loading={isSubmitting || isValidating}
            >
              {isValidating ? 'Validating...' : (editConfig ? 'Save Changes' : 'Add Configuration')}
            </Button>
          </div>
        </div>
      </form>
    </Modal>
  )
}
