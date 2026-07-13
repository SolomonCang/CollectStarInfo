export default function EmptyState({ compact, children }) {
  return (
    <div className={`empty-state${compact ? " compact-empty" : ""}`}>
      {children}
    </div>
  );
}
