import type {ReactNode} from 'react';
import {useNavigate} from 'react-router-dom';
import {NyayOneRevLLockup} from '../auth/NyayOneRevLIcon';
import {Icon} from '../internships/S20BrowseView';
import './S35Frame.css';

/** S-35 owns its shell; media adapters and server action contracts remain separate. */
export function S35Frame({children,dock,bare}:{screenId:string;children:ReactNode;dock?:ReactNode;bare?:boolean}){
 const navigate=useNavigate();
 return <div className={`v321-internships st-tutoring s35-lifecycle${bare?' s35-room':''}`} data-screen="S-35" data-v34-screen="S-35">
  {!bare&&<header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Sessions</span><div className="s20-lockup"><NyayOneRevLLockup/></div><nav aria-label="Site"><button onClick={()=>navigate('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span>Careers</span><button onClick={()=>navigate('/s-17')}>Profile</button></nav><button className="s20-avatar" aria-label="Your Profile" onClick={()=>navigate('/s-17')}><Icon name="person"/></button></header>}
  <div className="s20-layout"><main id="main-content">{children}{dock}</main>{!bare&&<aside aria-label="Session guidance"><section className="s20-card"><h2>Video and privacy</h2><p>Camera and microphone start only after you choose to test them. Joining requires server-issued credentials. Calls are not recorded.</p></section><section className="s20-card"><h2>Session changes</h2><p>The server checks the configured window, current version and attendance before accepting changes.</p></section></aside>}</div>
  {!bare&&<footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>}
 </div>;
}
