import React,{useEffect,useRef} from 'react';
import {Animated,Easing,View} from 'react-native';
import {voiceCallStyles as s} from './voice-call-styles';

export function VoiceOrb({muted=false,scale=1,opacity=.65,spin,spinRev}:{muted?:boolean;scale?:number|Animated.Value;opacity?:number|Animated.Value;spin?:Animated.AnimatedInterpolation<string>;spinRev?:Animated.AnimatedInterpolation<string>}) {
  const rotation=useRef(new Animated.Value(0)).current;
  useEffect(()=>{
    if(spin)return;
    const loop=Animated.loop(Animated.timing(rotation,{toValue:1,duration:9000,easing:Easing.linear,useNativeDriver:true}));
    loop.start();return()=>loop.stop();
  },[rotation,spin]);
  const forward=spin||rotation.interpolate({inputRange:[0,1],outputRange:['0deg','360deg']});
  const reverse=spinRev||rotation.interpolate({inputRange:[0,1],outputRange:['360deg','0deg']});
  return <View style={s.orbArea}><Animated.View style={[s.orb,{opacity:muted?.5:1,transform:[{scale}]}]}>
    <Animated.View style={[s.cloud,s.cloud1,{opacity,transform:[{rotate:forward}]}]}/>
    <Animated.View style={[s.cloud,s.cloud2,{opacity,transform:[{rotate:reverse}]}]}/>
    <Animated.View style={[s.cloud,s.cloud3,{opacity,transform:[{rotate:forward}]}]}/>
    <View style={s.gloss}/>
  </Animated.View></View>;
}
