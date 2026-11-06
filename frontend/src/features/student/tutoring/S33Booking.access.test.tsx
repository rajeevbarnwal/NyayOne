import {renderToStaticMarkup} from 'react-dom/server';
import {MemoryRouter} from 'react-router-dom';
import {expect,it} from 'vitest';
import {ANONYMOUS_AUTH,AuthProvider} from '../../../app/authContext';
import {S33Booking} from './S33Booking';
it('QA07 component explains non-student access without exposing booking actions',()=>{
 const html=renderToStaticMarkup(<MemoryRouter initialEntries={['/s-33?tutor=tutor-a&slot=slot-a']}><AuthProvider value={{...ANONYMOUS_AUTH,isAuthenticated:true,userId:'actor-a',roles:['tutor']}}><S33Booking/></AuthProvider></MemoryRouter>);
 expect(html).toContain('Booking is not available for this account.');
 expect(html).toContain('A student account is required');
 expect(html).toContain('No booking request was sent.');
 expect(html).not.toContain('Create payment order');
 expect(html).not.toContain('Booking confirmed.');
});
