import type { MDXComponents } from "mdx/types";

// Les guides utilisent le rendu Markdown standard ; la mise en forme vient de la classe .prose.
const composants: MDXComponents = {};

export function useMDXComponents(): MDXComponents {
  return composants;
}
