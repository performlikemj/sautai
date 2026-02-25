/**
 * StructuredContent - Renders structured JSON content blocks.
 * 
 * This component receives content from the Sous Chef AI assistant
 * and renders it as properly formatted HTML. It handles:
 * - Text blocks (paragraphs)
 * - Table blocks (with headers and rows)
 * - List blocks (ordered and unordered)
 * - Legacy markdown text (backwards compatibility with ReactMarkdown)
 */

import { useMemo, useState, useEffect, useRef } from 'react'
import DOMPurify from 'dompurify'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import ScaffoldPreview from './ScaffoldPreview.jsx'
import { api } from '../api.js'

/**
 * Check if content looks like markdown (has markdown syntax).
 */
function looksLikeMarkdown(content) {
  if (!content) return false
  // Check for common markdown patterns
  const markdownPatterns = [
    /\*\*[^*]+\*\*/,      // **bold**
    /\*[^*]+\*/,          // *italic*
    /^#{1,6}\s/m,         // # headers
    /^\s*[-*+]\s/m,       // - list items
    /^\s*\d+\.\s/m,       // 1. numbered lists
    /\[.+\]\(.+\)/,       // [links](url)
    /`[^`]+`/,            // `code`
    /^\|.+\|$/m,          // | tables |
  ]
  return markdownPatterns.some(pattern => pattern.test(content))
}

/**
 * Parse content and extract blocks.
 * Handles both structured JSON and legacy plain text/markdown.
 */
function parseContent(content) {
  if (!content) return { blocks: [], isLegacyMarkdown: false }
  
  // Try to parse as JSON
  try {
    let parsed = JSON.parse(content)
    
    // Handle array wrapper: [{"blocks": [...]}] -> {"blocks": [...]}
    if (Array.isArray(parsed)) {
      if (parsed.length > 0 && parsed[0] && Array.isArray(parsed[0].blocks)) {
        // Model returned [{"blocks": [...]}] - unwrap it
        parsed = parsed[0]
      } else if (parsed.length > 0 && parsed[0]?.type) {
        // Model returned blocks array directly: [{"type": "text", ...}]
        parsed = { blocks: parsed }
      }
    }
    
    if (parsed && Array.isArray(parsed.blocks)) {
      return { blocks: parsed.blocks, isLegacyMarkdown: false }
    }
    // If it's JSON but not our format, treat as legacy
    return { blocks: [], isLegacyMarkdown: true, rawContent: content }
  } catch {
    // Not JSON - this is legacy content
    return { blocks: [], isLegacyMarkdown: true, rawContent: content }
  }
}

/**
 * Preprocess markdown to fix missing newlines.
 * Some LLMs output markdown without proper line breaks.
 * This is a safety net - backend normalization should catch most cases.
 */
function preprocessMarkdown(text) {
  if (!text) return text

  let result = text

  // Convert <br> tags to newlines for better markdown parsing
  result = result.replace(/<br\s*\/?>/gi, '\n')

  // Fix inline list items by processing line by line
  // This avoids breaking table cells like "| Item - Value |"
  const lines = result.split('\n')
  const fixedLines = lines.map(line => {
    // Skip table rows (lines that start and end with |)
    const trimmed = line.trim()
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      return line
    }
    // Convert " - " to newline + "- " for list items
    let fixed = line.replace(/([.:!?])\s+-\s+/g, '$1\n\n- ')
    // Then handle any remaining " - " sequences
    fixed = fixed.replace(/\s+-\s+/g, '\n- ')
    return fixed
  })
  result = fixedLines.join('\n')

  // Add newline before headers (##, ###, etc.) if not at line start
  result = result.replace(/([^\n])(#{1,6}\s)/g, '$1\n\n$2')

  // Ensure double newline before headers for proper rendering
  result = result.replace(/\n(#{1,6}\s)/g, '\n\n$1')

  // Add newlines around table rows (| ... |)
  // First, add newline before table start (line starting with |)
  result = result.replace(/([^\n|])\s*(\|[^|]+\|)/g, '$1\n$2')

  // Add newline after table separator row (|---|)
  result = result.replace(/(\|[-:|\s]+\|)([^\n])/g, '$1\n$2')

  // Fix table rows concatenated on single line (but not separator rows)
  result = result.replace(/(\|[^|\n]+\|)\s*(?=\|[^-])/g, '$1\n')

  // Clean up excessive newlines (more than 2 in a row)
  result = result.replace(/\n{3,}/g, '\n\n')

  return result
}

/**
 * Render a text block.
 * Always uses ReactMarkdown since the assistant is instructed to use markdown.
 */
function TextBlock({ content }) {
  if (!content) return null

  // Convert content to string if it's not already (edge case: number or object)
  const textContent = typeof content === 'string' ? content : String(content)

  // Preprocess to fix malformed markdown (missing newlines)
  const processedContent = preprocessMarkdown(textContent)

  // Always use ReactMarkdown - the prompt instructs markdown output
  return (
    <div className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
        {processedContent}
      </ReactMarkdown>
    </div>
  )
}

/**
 * Render an HTML block with sanitization.
 * Used for pre-converted HTML from the backend (markdown -> HTML conversion).
 */
function HtmlBlock({ content }) {
  if (!content) return null

  // Sanitize HTML to prevent XSS attacks
  const sanitized = DOMPurify.sanitize(content, {
    ALLOWED_TAGS: [
      'p', 'br', 'strong', 'em', 'a', 'ul', 'ol', 'li',
      'code', 'pre', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr'
    ],
    ALLOWED_ATTR: ['href', 'title', 'target', 'rel', 'class']
  })

  return (
    <div
      className="html-content"
      dangerouslySetInnerHTML={{ __html: sanitized }}
    />
  )
}

/**
 * Format inline text with basic markdown-like patterns.
 * Handles **bold**, *italic*, `code`, and [links](url).
 */
function formatInlineText(text) {
  if (!text) return text
  
  // Simple inline formatting (without full markdown parser)
  const parts = []
  let remaining = text
  let key = 0
  
  // Pattern for **bold**, *italic*, `code`
  const patterns = [
    { regex: /\*\*([^*]+)\*\*/, tag: 'strong' },
    { regex: /\*([^*]+)\*/, tag: 'em' },
    { regex: /`([^`]+)`/, tag: 'code' },
  ]
  
  while (remaining) {
    let earliestMatch = null
    let earliestIndex = remaining.length
    let matchedPattern = null
    
    for (const pattern of patterns) {
      const match = remaining.match(pattern.regex)
      if (match && match.index < earliestIndex) {
        earliestMatch = match
        earliestIndex = match.index
        matchedPattern = pattern
      }
    }
    
    if (earliestMatch && matchedPattern) {
      // Add text before the match
      if (earliestIndex > 0) {
        parts.push(remaining.slice(0, earliestIndex))
      }
      // Add the formatted element
      const Tag = matchedPattern.tag
      parts.push(<Tag key={key++}>{earliestMatch[1]}</Tag>)
      remaining = remaining.slice(earliestIndex + earliestMatch[0].length)
    } else {
      // No more matches, add remaining text
      parts.push(remaining)
      break
    }
  }
  
  return parts.length === 1 ? parts[0] : parts
}

/**
 * Render a table block.
 * Handles edge cases: missing headers/rows, mismatched column counts, non-string cells.
 */
function TableBlock({ headers, rows }) {
  // Normalize headers to array
  const normalizedHeaders = Array.isArray(headers) ? headers : []
  const normalizedRows = Array.isArray(rows) ? rows : []
  
  // If no headers and no rows, don't render
  if (normalizedHeaders.length === 0 && normalizedRows.length === 0) return null
  
  // Determine column count (max of header length or any row length)
  const columnCount = Math.max(
    normalizedHeaders.length,
    ...normalizedRows.map(row => Array.isArray(row) ? row.length : 0)
  )
  
  // Pad headers if needed
  const paddedHeaders = [...normalizedHeaders]
  while (paddedHeaders.length < columnCount) {
    paddedHeaders.push('')
  }
  
  return (
    <div className="structured-table-wrapper">
      <table className="structured-table">
        {paddedHeaders.some(h => h) && (
          <thead>
            <tr>
              {paddedHeaders.map((header, i) => (
                <th key={i}>{String(header ?? '')}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {normalizedRows.map((row, rowIndex) => {
            // Ensure row is an array
            const rowArray = Array.isArray(row) ? row : [row]
            // Pad row to match column count
            const paddedRow = [...rowArray]
            while (paddedRow.length < columnCount) {
              paddedRow.push('')
            }
            
            return (
              <tr key={rowIndex}>
                {paddedRow.map((cell, cellIndex) => (
                  <td key={cellIndex}>{String(cell ?? '')}</td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Render a list block (ordered or unordered).
 * Handles edge cases: non-array items, nested arrays, non-string items.
 */
function ListBlock({ items, ordered }) {
  // Normalize items to array
  let normalizedItems = items
  if (!Array.isArray(normalizedItems)) {
    // Maybe it's a single item
    if (normalizedItems) {
      normalizedItems = [normalizedItems]
    } else {
      return null
    }
  }
  
  if (normalizedItems.length === 0) return null
  
  const ListTag = ordered ? 'ol' : 'ul'
  
  return (
    <ListTag className={`structured-list ${ordered ? 'ordered' : 'unordered'}`}>
      {normalizedItems.map((item, i) => (
        <li key={i}>
          {/* Handle nested arrays or objects */}
          {typeof item === 'object' && item !== null 
            ? JSON.stringify(item) 
            : String(item ?? '')
          }
        </li>
      ))}
    </ListTag>
  )
}

/**
 * Render an action block (navigation or form prefill button).
 * These are clickable buttons that trigger navigation or form actions.
 */
function ActionBlock({ action_type, label, payload, reason, onAction }) {
  // Icon based on action type
  const icon = action_type === 'navigate' ? '→' : '+'
  
  const handleClick = () => {
    if (onAction) {
      onAction({ action_type, payload })
    }
  }
  
  return (
    <div className="action-block">
      {reason && <p className="action-reason">{reason}</p>}
      <button 
        className="action-button"
        onClick={handleClick}
        type="button"
      >
        <span className="action-icon">{icon}</span>
        <span className="action-label">{label}</span>
      </button>
    </div>
  )
}

/**
 * Render a scaffold block (meal structure preview from AI).
 * Shows an interactive tree that can be edited and executed.
 */
function ScaffoldBlock({ scaffold: initialScaffold, summary, onAction }) {
  const [scaffold, setScaffold] = useState(initialScaffold)
  const [isExecuting, setIsExecuting] = useState(false)
  const [isFetchingIngredients, setIsFetchingIngredients] = useState(false)
  const [includeIngredients, setIncludeIngredients] = useState(false)
  const [executed, setExecuted] = useState(false)
  const [result, setResult] = useState(null)
  
  // Toggle ingredients - re-fetch scaffold with ingredients included
  const handleToggleIngredients = async (enabled) => {
    setIncludeIngredients(enabled)
    
    if (enabled && scaffold) {
      // Re-fetch with ingredients
      setIsFetchingIngredients(true)
      try {
        const mealName = scaffold.data?.name || ''
        const mealType = scaffold.data?.meal_type || 'Dinner'
        
        const response = await api.post('/chefs/api/me/sous-chef/scaffold/generate/', {
          hint: mealName,
          include_dishes: true,
          include_ingredients: true,
          meal_type: mealType
        })
        
        if (response.data.status === 'success') {
          setScaffold(response.data.scaffold)
        }
      } catch (err) {
        console.error('[Scaffold] Ingredient fetch failed:', err)
      } finally {
        setIsFetchingIngredients(false)
      }
    } else if (!enabled && scaffold) {
      // Remove ingredients from scaffold
      const removeIngredients = (item) => {
        if (item.type === 'dish') {
          return { ...item, children: [] }
        }
        return {
          ...item,
          children: (item.children || []).map(removeIngredients)
        }
      }
      setScaffold(removeIngredients(scaffold))
    }
  }
  
  const handleExecute = async () => {
    if (!scaffold) return
    
    setIsExecuting(true)
    try {
      const response = await api.post('/chefs/api/me/sous-chef/scaffold/execute/', { scaffold })
      
      if (response.data.status === 'success') {
        setExecuted(true)
        setResult(response.data)
        
        // Notify parent to update UI (e.g., refresh dishes list)
        if (onAction) {
          onAction({ 
            action_type: 'scaffold_executed', 
            payload: response.data 
          })
        }
      } else {
        throw new Error(response.data.message || 'Failed to execute scaffold')
      }
    } catch (err) {
      console.error('[Scaffold] Execution failed:', err)
      alert('Failed to create items: ' + (err.message || 'Unknown error'))
    } finally {
      setIsExecuting(false)
    }
  }
  
  // If already executed, show success message
  if (executed && result) {
    const { summary: resultSummary } = result
    return (
      <div className="scaffold-success-block">
        <span className="scaffold-success-icon">✅</span>
        <span className="scaffold-success-text">
          Created {resultSummary.dishes} dish{resultSummary.dishes !== 1 ? 'es' : ''}
          {resultSummary.ingredients > 0 && ` with ${resultSummary.ingredients} ingredient${resultSummary.ingredients !== 1 ? 's' : ''}`}!
        </span>
      </div>
    )
  }
  
  if (!scaffold) return null
  
  return (
    <div className="scaffold-block-container">
      <ScaffoldPreview
        scaffold={scaffold}
        onUpdate={setScaffold}
        includeIngredients={includeIngredients}
        onToggleIngredients={handleToggleIngredients}
        isFetchingIngredients={isFetchingIngredients}
        onExecute={handleExecute}
        onCancel={() => setScaffold(null)}
        isExecuting={isExecuting}
      />
    </div>
  )
}

/**
 * Main StructuredContent component.
 * 
 * @param {Object} props
 * @param {string} props.content - The content string (JSON or plain text)
 * @param {string} props.className - Optional additional CSS class
 * @param {function} props.onAction - Optional callback for action blocks (navigation/prefill)
 */
export default function StructuredContent({ content, className = '', onAction }) {
  // Parse content to blocks or detect legacy markdown
  const parsed = useMemo(() => parseContent(content), [content])

  // Track which auto-execute actions we've already executed to avoid duplicates
  const executedActionsRef = useRef(new Set())

  // Auto-execute actions that have auto_execute: true
  useEffect(() => {
    if (!parsed.blocks || !onAction) return

    for (const block of parsed.blocks) {
      if (block?.type === 'action' && block.auto_execute) {
        // Create a unique key for this action to avoid re-executing
        const actionKey = `${block.action_type}-${block.payload?.tab || ''}-${block.payload?.form_type || ''}`

        if (!executedActionsRef.current.has(actionKey)) {
          executedActionsRef.current.add(actionKey)
          // Execute the action
          onAction({ action_type: block.action_type, payload: block.payload })
        }
      }
    }
  }, [parsed.blocks, onAction])
  
  // Handle legacy markdown content with ReactMarkdown
  if (parsed.isLegacyMarkdown) {
    const processedContent = preprocessMarkdown(parsed.rawContent || '')
    return (
      <div className={`structured-content legacy-markdown ${className}`}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
          {processedContent}
        </ReactMarkdown>
        <style>{legacyMarkdownStyles}</style>
      </div>
    )
  }
  
  const { blocks } = parsed
  
  // Handle empty blocks - show nothing rather than error
  if (!blocks || blocks.length === 0) {
    return <div className={`structured-content empty ${className}`} />
  }
  
  return (
    <div className={`structured-content ${className}`}>
      {blocks.map((block, index) => {
        // Handle null/undefined blocks
        if (!block) return null
        
        // Get block type, defaulting to 'text' for unknown types
        const blockType = block.type || 'text'
        
        switch (blockType) {
          case 'table':
            return (
              <TableBlock
                key={index}
                headers={block.headers}
                rows={block.rows}
              />
            )
          
          case 'list':
            return (
              <ListBlock
                key={index}
                items={block.items}
                ordered={block.ordered}
              />
            )
          
          case 'code':
            // Handle code blocks (edge case: model might use this type)
            return (
              <pre key={index} className="structured-code">
                <code>{String(block.content || block.code || '')}</code>
              </pre>
            )
          
          case 'heading':
            // Handle heading blocks (edge case: model might use this type)
            const HeadingTag = `h${Math.min(Math.max(block.level || 3, 1), 6)}`
            return <HeadingTag key={index}>{String(block.content || block.text || '')}</HeadingTag>
          
          case 'action':
            // Handle action blocks (navigation or form prefill buttons)
            return (
              <ActionBlock
                key={index}
                action_type={block.action_type}
                label={block.label}
                payload={block.payload}
                reason={block.reason}
                onAction={onAction}
              />
            )
          
          case 'scaffold':
            // Handle scaffold blocks (meal structure from AI)
            return (
              <ScaffoldBlock
                key={index}
                scaffold={block.scaffold}
                summary={block.summary}
                onAction={onAction}
              />
            )

          case 'html':
            // Handle HTML blocks (pre-converted from markdown by backend)
            return <HtmlBlock key={index} content={block.content} />

          case 'text':
          default:
            // For unknown types, try to extract content from various possible fields
            const textContent = block.content || block.text || block.value || 
                               (typeof block === 'string' ? block : JSON.stringify(block))
            return <TextBlock key={index} content={textContent} />
        }
      })}
      
      <style>{`
        .structured-content {
          line-height: 1.6;
          color: var(--text);
          font-size: 0.9rem;
          word-break: break-word;
        }
        
        .structured-text {
          margin: 0.75em 0;
          color: var(--text);
        }
        
        .structured-text:first-child { margin-top: 0; }
        .structured-text:last-child { margin-bottom: 0; }
        
        /* Table Styles */
        .structured-table-wrapper {
          overflow-x: auto;
          margin: 0.75em 0;
        }
        
        .structured-table {
          border-collapse: collapse;
          font-size: 0.85em;
          width: 100%;
          min-width: 300px;
        }
        
        .structured-table th {
          background: var(--surface-2, #f3f4f6);
          border: 1px solid var(--border, #e5e7eb);
          padding: 0.5em 0.75em;
          color: var(--text);
          font-weight: 600;
          text-align: left;
          white-space: nowrap;
        }
        
        .structured-table td {
          border: 1px solid var(--border, #e5e7eb);
          padding: 0.5em 0.75em;
          color: var(--text);
          vertical-align: top;
        }
        
        .structured-table tbody tr:nth-child(even) {
          background: rgba(128, 128, 128, 0.05);
        }
        
        .structured-table tbody tr:hover {
          background: rgba(124, 144, 112, 0.08);
        }
        
        /* List Styles */
        .structured-list {
          margin: 0.75em 0;
          padding-left: 1.5em;
          color: var(--text);
        }
        
        .structured-list li {
          margin: 0.35em 0;
          line-height: 1.5;
        }
        
        .structured-list.unordered { list-style-type: disc; }
        .structured-list.ordered { list-style-type: decimal; }
        
        /* Code Block Styles */
        .structured-code {
          background: var(--surface-2, #f3f4f6);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 6px;
          padding: 0.75em 1em;
          margin: 0.75em 0;
          overflow-x: auto;
          font-family: 'SF Mono', Monaco, 'Courier New', monospace;
          font-size: 0.85em;
          line-height: 1.5;
          color: var(--text);
        }
        
        .structured-code code {
          background: transparent;
          padding: 0;
          font-size: inherit;
        }
        
        /* Inline code in text */
        .structured-text code {
          background: var(--surface-2, #f3f4f6);
          padding: 0.15em 0.35em;
          border-radius: 3px;
          font-family: 'SF Mono', Monaco, 'Courier New', monospace;
          font-size: 0.9em;
        }
        
        /* Bold/italic in text */
        .structured-text strong { font-weight: 600; }
        .structured-text em { font-style: italic; }
        
        /* First/last element spacing */
        .structured-content > *:first-child { margin-top: 0 !important; }
        .structured-content > *:last-child { margin-bottom: 0 !important; }

        /* Markdown Content (ReactMarkdown rendered) */
        .markdown-content {
          line-height: 1.6;
          color: var(--text);
        }

        .markdown-content p {
          margin: 0.75em 0;
          color: var(--text);
        }

        .markdown-content p:first-child { margin-top: 0; }
        .markdown-content p:last-child { margin-bottom: 0; }

        .markdown-content h1,
        .markdown-content h2,
        .markdown-content h3,
        .markdown-content h4 {
          color: var(--text);
          font-weight: 600;
          line-height: 1.3;
          margin-top: 1.25em;
          margin-bottom: 0.5em;
        }

        .markdown-content h1 { font-size: 1.3em; }
        .markdown-content h2 { font-size: 1.15em; }
        .markdown-content h3 { font-size: 1.05em; }
        .markdown-content h4 { font-size: 1em; }

        .markdown-content h1:first-child,
        .markdown-content h2:first-child,
        .markdown-content h3:first-child { margin-top: 0; }

        .markdown-content ul,
        .markdown-content ol {
          margin: 0.75em 0;
          padding-left: 1.5em;
          color: var(--text);
        }

        .markdown-content li {
          margin: 0.35em 0;
          line-height: 1.5;
          color: var(--text);
        }

        .markdown-content ul { list-style-type: disc; }
        .markdown-content ol { list-style-type: decimal; }

        .markdown-content strong { font-weight: 700; color: var(--text); }
        .markdown-content em { font-style: italic; }

        .markdown-content code {
          background: var(--surface-2, #f3f4f6);
          border: 1px solid var(--border, #e5e7eb);
          padding: 0.15em 0.4em;
          border-radius: 4px;
          font-size: 0.85em;
        }

        .markdown-content pre {
          background: var(--surface-2, #f3f4f6);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 6px;
          padding: 0.75em 1em;
          margin: 0.75em 0;
          overflow-x: auto;
        }

        .markdown-content pre code {
          background: transparent;
          border: none;
          padding: 0;
        }

        .markdown-content table {
          border-collapse: collapse;
          margin: 0.75em 0;
          font-size: 0.85em;
          width: 100%;
        }

        .markdown-content th {
          background: var(--surface-2, #f3f4f6);
          border: 1px solid var(--border, #e5e7eb);
          padding: 0.5em 0.75em;
          color: var(--text);
          font-weight: 600;
          text-align: left;
        }

        .markdown-content td {
          border: 1px solid var(--border, #e5e7eb);
          padding: 0.5em 0.75em;
          color: var(--text);
        }

        .markdown-content tbody tr:nth-child(even) {
          background: rgba(128, 128, 128, 0.05);
        }

        .markdown-content > *:first-child { margin-top: 0 !important; }
        .markdown-content > *:last-child { margin-bottom: 0 !important; }

        /* HTML Content (pre-converted from markdown by backend) */
        .html-content {
          display: block;
          line-height: 1.6;
          color: var(--text);
        }

        .html-content strong { font-weight: 700; color: var(--text); }
        .html-content em { font-style: italic; }

        .html-content a {
          color: var(--primary, #7C9070);
          text-decoration: none;
        }

        .html-content a:hover {
          text-decoration: underline;
        }

        .html-content code {
          background: var(--surface-2, #f3f4f6);
          border: 1px solid var(--border, #e5e7eb);
          padding: 0.15em 0.4em;
          border-radius: 4px;
          font-size: 0.85em;
          font-family: 'SF Mono', Monaco, 'Courier New', monospace;
        }

        .html-content pre {
          background: var(--surface-2, #f3f4f6);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 6px;
          padding: 0.75em 1em;
          margin: 0.75em 0;
          overflow-x: auto;
        }

        .html-content pre code {
          background: transparent;
          border: none;
          padding: 0;
        }

        .html-content ul,
        .html-content ol {
          display: block;
          margin: 0.75em 0;
          padding-left: 1.5em;
          color: var(--text);
        }

        .html-content li {
          display: list-item;
          margin: 0.35em 0;
          line-height: 1.5;
          color: var(--text);
        }

        .html-content ul { list-style-type: disc; }
        .html-content ol { list-style-type: decimal; }

        /* Table styles - use !important to override any inherited flex/block display */
        .html-content table {
          display: table !important;
          border-collapse: collapse !important;
          border-spacing: 0 !important;
          margin: 0.75em 0;
          font-size: 0.85em;
          width: 100%;
          table-layout: auto;
        }

        .html-content thead {
          display: table-header-group !important;
        }

        .html-content tbody {
          display: table-row-group !important;
        }

        .html-content tr {
          display: table-row !important;
        }

        .html-content th {
          display: table-cell !important;
          background: var(--surface-2, #f3f4f6);
          border: 1px solid var(--border, #e5e7eb);
          padding: 0.5em 0.75em;
          color: var(--text);
          font-weight: 600;
          text-align: left;
          vertical-align: top;
        }

        .html-content td {
          display: table-cell !important;
          border: 1px solid var(--border, #e5e7eb);
          padding: 0.5em 0.75em;
          color: var(--text);
          vertical-align: top;
        }

        .html-content tbody tr:nth-child(even) {
          background: rgba(128, 128, 128, 0.05);
        }

        .html-content hr {
          border: none;
          border-top: 1px solid var(--border, #e5e7eb);
          margin: 1em 0;
        }

        .html-content > *:first-child { margin-top: 0 !important; }
        .html-content > *:last-child { margin-bottom: 0 !important; }

        /* Action Block Styles */
        .action-block {
          margin: 0.75em 0;
          padding: 0.75em;
          background: linear-gradient(135deg, rgba(124, 144, 112, 0.08), rgba(124, 144, 112, 0.04));
          border: 1px solid rgba(124, 144, 112, 0.2);
          border-radius: 8px;
        }
        
        .action-reason {
          margin: 0 0 0.5em 0;
          font-size: 0.85em;
          color: var(--text);
          line-height: 1.4;
        }
        
        .action-button {
          display: inline-flex;
          align-items: center;
          gap: 0.5em;
          padding: 0.6em 1.2em;
          background: linear-gradient(135deg, var(--primary, #7C9070), var(--primary-700, #5A6C52));
          color: white;
          border: none;
          border-radius: 6px;
          font-size: 0.9em;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
          box-shadow: 0 2px 4px rgba(124, 144, 112, 0.2);
        }
        
        .action-button:hover {
          transform: translateY(-1px);
          box-shadow: 0 4px 8px rgba(124, 144, 112, 0.3);
        }
        
        .action-button:active {
          transform: translateY(0);
          box-shadow: 0 1px 2px rgba(124, 144, 112, 0.2);
        }
        
        .action-icon {
          font-size: 1.1em;
          font-weight: 600;
        }
        
        .action-label {
          font-weight: 500;
        }
        
        /* Scaffold Block Styles */
        .scaffold-block-container {
          margin: 0.75em 0;
        }
        
        .scaffold-block-container .scaffold-preview {
          max-width: 100%;
          box-shadow: var(--shadow-sm);
        }
        
        .scaffold-success-block {
          display: flex;
          align-items: center;
          gap: 0.5em;
          padding: 0.75em 1em;
          background: linear-gradient(135deg, rgba(124, 144, 112, 0.12), rgba(124, 144, 112, 0.06));
          border: 1px solid rgba(124, 144, 112, 0.35);
          border-radius: var(--radius, 8px);
          margin: 0.75em 0;
        }
        
        .scaffold-success-icon {
          font-size: 1.1em;
        }
        
        .scaffold-success-text {
          color: var(--primary, #7C9070);
          font-weight: 500;
        }
        
        /* Dark theme scaffold success */
        [data-theme="dark"] .scaffold-success-block {
          background: linear-gradient(135deg, rgba(124, 144, 112, 0.18), rgba(124, 144, 112, 0.08));
          border-color: rgba(124, 144, 112, 0.4);
        }
      `}</style>
    </div>
  )
}

/**
 * Styles for legacy markdown content rendered with ReactMarkdown.
 */
const legacyMarkdownStyles = `
  .legacy-markdown {
    line-height: 1.6;
    color: var(--text);
    font-size: 0.9rem;
    word-break: break-word;
  }
  
  .legacy-markdown p {
    margin: 0.75em 0;
    color: var(--text);
  }
  
  .legacy-markdown p:first-child { margin-top: 0; }
  .legacy-markdown p:last-child { margin-bottom: 0; }
  
  .legacy-markdown h1,
  .legacy-markdown h2,
  .legacy-markdown h3,
  .legacy-markdown h4 {
    color: var(--text);
    font-weight: 600;
    line-height: 1.3;
    margin-top: 1.25em;
    margin-bottom: 0.5em;
  }
  
  .legacy-markdown h1 { font-size: 1.3em; }
  .legacy-markdown h2 { font-size: 1.15em; }
  .legacy-markdown h3 { font-size: 1.05em; }
  .legacy-markdown h4 { font-size: 1em; }
  
  .legacy-markdown h1:first-child,
  .legacy-markdown h2:first-child,
  .legacy-markdown h3:first-child { margin-top: 0; }
  
  .legacy-markdown ul,
  .legacy-markdown ol {
    margin: 0.75em 0;
    padding-left: 1.5em;
    color: var(--text);
  }
  
  .legacy-markdown li {
    margin: 0.35em 0;
    line-height: 1.5;
    color: var(--text);
  }
  
  .legacy-markdown ul { list-style-type: disc; }
  .legacy-markdown ol { list-style-type: decimal; }
  
  .legacy-markdown strong { font-weight: 700; color: var(--text); }
  .legacy-markdown em { font-style: italic; }
  
  .legacy-markdown code {
    background: var(--surface-2, #f3f4f6);
    border: 1px solid var(--border, #e5e7eb);
    padding: 0.15em 0.4em;
    border-radius: 4px;
    font-size: 0.85em;
  }
  
  .legacy-markdown pre {
    background: var(--surface-2, #f3f4f6);
    border: 1px solid var(--border, #e5e7eb);
    border-radius: 6px;
    padding: 0.75em 1em;
    margin: 0.75em 0;
    overflow-x: auto;
  }
  
  .legacy-markdown pre code {
    background: transparent;
    border: none;
    padding: 0;
  }
  
  .legacy-markdown table {
    border-collapse: collapse;
    margin: 0.75em 0;
    font-size: 0.85em;
    width: 100%;
    display: block;
    overflow-x: auto;
  }
  
  .legacy-markdown th {
    background: var(--surface-2, #f3f4f6);
    border: 1px solid var(--border, #e5e7eb);
    padding: 0.5em 0.75em;
    color: var(--text);
    font-weight: 600;
    text-align: left;
  }
  
  .legacy-markdown td {
    border: 1px solid var(--border, #e5e7eb);
    padding: 0.5em 0.75em;
    color: var(--text);
  }
  
  .legacy-markdown tbody tr:nth-child(even) {
    background: rgba(128, 128, 128, 0.05);
  }
  
  .legacy-markdown > *:first-child { margin-top: 0 !important; }
  .legacy-markdown > *:last-child { margin-bottom: 0 !important; }
`

/**
 * Export parsing utility for use in other components.
 */
export { parseContent }
