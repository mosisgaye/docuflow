import type { MetadataRoute } from "next";
import { SITE } from "@/contenu/site";

export default function robots(): MetadataRoute.Robots {
  // L'application et l'API ne sont pas des pages à référencer.
  return { rules: { userAgent: "*", allow: "/", disallow: ["/api/"] }, sitemap: `${SITE.adresse}/sitemap.xml` };
}
