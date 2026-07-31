export default function ErrorBanner({ message, onRetry }) {
  if (!message) return null;
  return (
    <div className="error-banner" role="alert" aria-live="assertive">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="ghost-button error-retry" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}
