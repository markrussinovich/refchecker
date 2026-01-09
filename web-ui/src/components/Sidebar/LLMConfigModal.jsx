import { useState, useEffect } from 'react'
import Modal from '../common/Modal'
import Button from '../common/Button'
import { useConfigStore } from '../../stores/useConfigStore'
import { validateLLMConfig } from '../../utils/api'
import { logger } from '../../utils/logger'

const PROVIDERS = [
  { id: 'openai', name: 'OpenAI', defaultModel: 'gpt-4o', requiresKey: true },
  { id: 'anthropic', name: 'Anthropic', defaultModel: 'claude-3-5-sonnet-latest', requiresKey: true },
  { id: 'google', name: 'Google', defaultModel: 'gemini-1.5-flash', requiresKey: true },
  { id: 'azure', name: 'Azure OpenAI', defaultModel: 'gpt-4o', requiresKey: true, requiresEndpoint: true },
  { id: 'vllm', name: 'vLLM (Local)', defaultModel: 'meta-llama/Llama-3.1-8B-Instruct', requiresKey: false, requiresEndpoint: true },
]

/**
 * Modal for adding/editing LLM configurations
 */
export default function LLMConfigModal({ isOpen, onClose, editConfig = null }) {
  const { addConfig, updateConfig } = useConfigStore()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [error, setError] = useState(null)

  const [formData, setFormData] = useState({
    name: '',
    provider: 'anthropic',
    model: '',
    api_key: '',
    endpoint: '',
  })

  // Reset form when modal opens/closes or editConfig changes
  useEffect(() => {
    if (isOpen) {
      setFormData({
        name: editConfig?.name || '',
        provider: editConfig?.provider || 'anthropic',
        model: editConfig?.model || '',
        api_key: '',
        endpoint: editConfig?.endpoint || '',
      })
      setError(null)
    }
  }, [isOpen, editConfig])

  const selectedProvider = PROVIDERS.find(p => p.id === formData.provider)

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
    setError(null)
  }

  const handleProviderChange = (e) => {
    const provider = e.target.value
    const providerInfo = PROVIDERS.find(p => p.id === provider)
    setFormData(prev => ({
      ...prev,
      provider,
      model: '', // Reset model when provider changes
      endpoint: provider === 'vllm' ? 'http://localhost:8000' : prev.endpoint,
    }))
    setError(null)
  }

  const validate = () => {
    if (!formData.name.trim()) {
      setError('Name is required')
      return false
    }

    if (selectedProvider?.requiresKey && !editConfig && !formData.api_key.trim()) {
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
      const configData = {
        name: formData.name.trim(),
        provider: formData.provider,
        model: formData.model.trim() || selectedProvider?.defaultModel || null,
        endpoint: formData.endpoint.trim() || null,
      }

      // Only include API key if it was entered
      if (formData.api_key.trim()) {
        configData.api_key = formData.api_key.trim()
      }

      // Validate API connection before saving (only for new configs or when API key is provided)
      if (selectedProvider?.requiresKey && (formData.api_key.trim() || !editConfig)) {
        setIsValidating(true)
        try {
          const validationData = {
            provider: configData.provider,
            model: configData.model,
            api_key: configData.api_key,
            endpoint: configData.endpoint,
          }
          logger.info('LLMConfigModal', 'Validating API connection...', { provider: configData.provider, model: configData.model })
          const response = await validateLLMConfig(validationData)
          if (!response.data.valid) {
            throw new Error(response.data.error || 'API validation failed')
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

      if (editConfig) {
        await updateConfig(editConfig.id, configData)
        logger.info('LLMConfigModal', 'Config updated')
      } else {
        await addConfig(configData)
        logger.info('LLMConfigModal', 'Config created')
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
        {/* Name */}
        <div>
          <label 
            htmlFor="name"
            className="block text-sm font-medium mb-1"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Configuration Name
          </label>
          <input
            type="text"
            id="name"
            name="name"
            value={formData.name}
            onChange={handleChange}
            placeholder="e.g., My GPT-4"
            className="w-full px-3 py-2 rounded-lg border focus:outline-none focus:ring-2"
            style={{
              backgroundColor: 'var(--color-bg-secondary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          />
        </div>

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
            {PROVIDERS.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        {/* Model */}
        <div>
          <label 
            htmlFor="model"
            className="block text-sm font-medium mb-1"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Model
            <span 
              className="ml-1 font-normal"
              style={{ color: 'var(--color-text-muted)' }}
            >
              (optional)
            </span>
          </label>
          <input
            type="text"
            id="model"
            name="model"
            value={formData.model}
            onChange={handleChange}
            placeholder={selectedProvider?.defaultModel || 'Default model'}
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
            Default: {selectedProvider?.defaultModel}
          </p>
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
              placeholder={editConfig ? '••••••••' : 'Enter API key'}
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
              Stored securely and never shown again
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

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-2">
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
      </form>
    </Modal>
  )
}
