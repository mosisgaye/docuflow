/** Un champ à remplir avant la mise en ligne : bien visible, pour ne pas l'oublier. */
export function ACompleter({ children }: { children: React.ReactNode }) {
  return <span className="a-completer">[À COMPLÉTER : {children}]</span>;
}
