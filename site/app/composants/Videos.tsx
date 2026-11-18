"use client";

import { useState } from "react";
import { VIDEOS, type Video } from "@/contenu/videos";
import { Jouer } from "./Icones";

const integree = (source: string) => /^https?:\/\//.test(source);

function Lecteur({ video }: { video: Video }) {
  return integree(video.source) ? (
    <iframe className="lecteur" src={video.source} title={video.titre} allow="autoplay; fullscreen; picture-in-picture" allowFullScreen />
  ) : (
    <video className="lecteur lecteur--video" src={video.source} poster={video.vignette} controls autoPlay muted playsInline preload="metadata" aria-label={video.titre} />
  );
}

/** Les vidéos de présentation. Rien n'est affiché tant que contenu/videos.ts est vide. */
export function Videos() {
  const [choisie, setChoisie] = useState<number | null>(null);
  if (VIDEOS.length === 0) return null;
  const [grande, ...extraits] = VIDEOS;

  return (
    <section className="section" id="videos" style={{ paddingTop: 0 }}>
      <div className="conteneur">
        <div className="section__tete">
          <h2>Voyez Verifac travailler.</h2>
          <p className="chapo">Le tour de Verifac en moins d’une minute, puis trois moments précis.</p>
        </div>
        <div className="videos">
          {choisie !== null ? (
            <Lecteur video={VIDEOS[choisie]} />
          ) : (
            <button className="lecteur" type="button" onClick={() => setChoisie(0)} aria-label={`Lire la vidéo : ${grande.titre}`} style={{ backgroundImage: `url(${grande.vignette})`, backgroundSize: "cover" }}>
              <span className="lecteur__jouer">
                <Jouer />
              </span>
              <span className="lecteur__legende">
                <strong>{grande.titre}</strong>
                <span>{grande.resume}</span>
              </span>
            </button>
          )}
          {extraits.length > 0 && (
            <div className="extraits">
              {extraits.map((video, rang) => (
                <button key={video.titre} className="extrait" type="button" onClick={() => setChoisie(rang + 1)}>
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
          )}
        </div>
      </div>
    </section>
  );
}
