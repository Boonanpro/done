import {useEffect,useState} from 'react';
import {Platform,StatusBar} from 'react-native';
import * as NavigationBar from 'expo-navigation-bar';

let changes=Promise.resolve();
const nextFrame=()=>new Promise<void>(resolve=>requestAnimationFrame(()=>resolve()));

// Android's Modal copies the activity's system bars when its window opens.
// Prepare immersive mode first; restore the previous state after dismissal.
export function useMediaImmersive(){
 const [ready,setReady]=useState(false);
 useEffect(()=>{
  let active=true;
  let previous:NavigationBar.NavigationBarVisibility='visible';
  const status=StatusBar.pushStackEntry({hidden:true,animated:false});
  changes=changes.then(async()=>{
   if(Platform.OS==='android'){
    previous=await NavigationBar.getVisibilityAsync();
    await NavigationBar.setVisibilityAsync('hidden');
   }
   await nextFrame();await nextFrame();
  }).catch(error=>console.warn('Media system bars:',error)).then(()=>{if(active)setReady(true)});
  return ()=>{
   active=false;
   StatusBar.popStackEntry(status);
   changes=changes.then(async()=>{if(Platform.OS==='android')await NavigationBar.setVisibilityAsync(previous)}).catch(error=>console.warn('Restore system bars:',error));
  };
 },[]);
 return ready;
}
