import { Composition } from "remotion";
import { YoshikawaProposal } from "./YoshikawaProposal";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="YoshikawaProposal"
      component={YoshikawaProposal}
      durationInFrames={840}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
