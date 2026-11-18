/** Les vidéos de présentation. Tant que la liste est vide, la section Vidéos n'apparaît pas sur le site.
 *
 *  Pour en ajouter une : déposer le fichier (ou une adresse YouTube/Vimeo) et sa vignette, puis une ligne ici.
 *  La première est la grande vidéo ; les suivantes sont les extraits courts.
 */
export type Video = {
  titre: string;
  resume: string;
  duree: string; // « 3:00 », « 0:30 »
  source: string; // /videos/fichier.mp4 ou adresse d'intégration
  vignette: string; // /videos/vignette.jpg
  secondes: number; // pour les données structurées (VideoObject)
  publiee: string; // AAAA-MM-JJ
};

// Enregistrées sur l'application avec des données fictives. Fichiers dans public/videos/ (MP4 H.264, sans son).
export const VIDEOS: Video[] = [
  { titre: "Verifac en 43 secondes", resume: "Accueil, circuit, connecteurs, et une facture à approuver", duree: "0:43", source: "/videos/verifac-demo.mp4", vignette: "/videos/verifac-demo.jpg", secondes: 43, publiee: "2026-11-18" },
  { titre: "Dessiner le circuit d’approbation", resume: "Conditions, niveaux, IBAN changé", duree: "0:06", source: "/videos/circuit.mp4", vignette: "/videos/circuit.jpg", secondes: 6, publiee: "2026-11-18" },
  { titre: "Brancher Odoo et HubSpot", resume: "Les connecteurs, en lecture seule", duree: "0:09", source: "/videos/connecteurs.mp4", vignette: "/videos/connecteurs.jpg", secondes: 9, publiee: "2026-11-18" },
  { titre: "Les factures à votre tour", resume: "Approuver ou rejeter, la facture à côté", duree: "0:08", source: "/videos/mon-tour.mp4", vignette: "/videos/mon-tour.jpg", secondes: 8, publiee: "2026-11-18" },
];
