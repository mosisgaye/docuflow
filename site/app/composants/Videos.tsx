"use client";

import { useEffect, useRef, useState } from "react";
import { VIDEOS, type Video } from "@/contenu/videos";
import { Jouer } from "./Icones";

const integree = (source: string) => /^https?:\/\//.test(source);

/** Le lecteur : une vidéo du site démarre seule, sans son, dès qu'elle est à l'écran, et se met en pause quand on s'en éloigne.
 *  Elle ne se charge qu'à ce moment-là. Mouvement réduit demandé : rien ne démarre seul, les commandes restent là. */
function Lecteur({ video }: { video: Video }) {
  const element = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const lecteur = element.current;
    if (!lecteur || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const observateur = new IntersectionObserver(
      ([entree]) => {
        if (entree.isIntersecting) lecteur.play().catch(() => {});
        else lecteur.pause();
      },
      { threshold: 0.4 },
    );
    observateur.observe(lecteur);
    return () => observateur.disconnect();
  }, [video.source]);

  return integree(video.source) ? (
    <iframe className="lecteur" src={video.source} title={video.titre} allow="autoplay; fullscreen; picture-in-picture" allowFullScreen />
  ) : (
    <video
      ref={element}
      key={video.source}
      className="lecteur lecteur--video"
      src={video.source}
      poster={video.vignette}
      controls
      muted
      loop
      playsInline
      preload="none"
      aria-label={video.titre}
    />
  );
}

/** Les vidéos de présentation. Rien n'est affiché tant que contenu/videos.ts est vide. */
export function Videos() {
  const [choisie, setChoisie] = useState(0);
  if (VIDEOS.length === 0) return null;
  const extraits = VIDEOS.map((video, rang) => ({ video, rang })).filter(({ rang }) => rang !== choisie);

  return (
    <section className="section" id="videos" style={{ paddingTop: 0 }}>
      <div className="conteneur">
        <div className="section__tete">
          <h2>Voyez Verifac travailler.</h2>
          <p className="chapo">Le tour de Verifac en moins d’une minute, puis trois moments précis.</p>
        </div>
        <div className="videos">
          <Lecteur video={VIDEOS[choisie]} />
          <div className="extraits">
            {extraits.map(({ video, rang }) => (
              <button key={video.titre} className="extrait" type="button" onClick={() => setChoisie(rang)}>
                <span className="extrait__vignette" style={{ backgroundImage: `url(${video.vignette})`, backgroundSize: "cover" }}>
                  <Jouer taille={18} />
                  <em>{video.duree}</em>
                </span>
                <span>
                  <strong>{video.titre}</strong>
                  <span>{video.resume}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
