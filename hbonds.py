import numpy as np
import re


def map_w_to_index(t, t_red, idx_file, atom_mapping, verbose=False):
    '''
    Map water name to index in each frame of reduced trajectory.

    This function maps the indices of water residues in a reduced trajectory to
    water letter codes corresponding to water oxygen atom indices of the whole
    trajectory, mapped by track_s1_water. This applies to water reduced
    trajectories generated by the dynamic search of remove_far_waters and
    tracked s1 pocket water with track_s1_water.

    Parameters
    ----------
    t : md.Trajectory
        Whole trajectory on which track_s1_water was run.
    t_red : md.Trajectory
        Reduced trajectory generated by dynamic search of remove_far_waters.
    idx_file : str
        Path to water indices file generated by remove_far_waters.
    atom_mapping : dict
        Mapping of water atom indices to water letter codes as generated by
        track_s1_water. The keys need to be the water letter codes and values
        numpy arrays of shape (n_frames,) that hold the water oxygen atom
        indices for each frame.
    verbose : bool
        Verbose mode.
    '''
    # water residue indices in reduced and whole/actual trajectory
    wrid_red = [r.index for r in t_red.top.residues if r.is_water]
    wrid_whole = np.loadtxt(idx_file).astype('int')

    # enforce integer type on mapping
    for key in atom_mapping:
        atom_mapping[key] = atom_mapping[key].astype('int')

    # list of letter codes from mapping
    letter_codes = [x for x in atom_mapping.keys()]

    # assign water residue indices of whole trj to letter codes
    wrid_letters = {}
    for wl in letter_codes:
        wrid_letters[wl] = np.array([t.top.atom(x).residue.index for x in atom_mapping[wl]])

    # map water residue indices of reduced trj to letter codes
    mapping_res = {}
    for wl in letter_codes:
        mapping_res[wl] = np.zeros(t.n_frames, dtype=int)
        for i_frame in range(t.n_frames):
            wrid = wrid_letters[wl][i_frame]
            if wrid in wrid_whole[i_frame]:
                res_idx, = np.where(wrid_whole[i_frame] == wrid)
                if len(res_idx) == 1:
                    res_idx = res_idx[0]
                else:
                    raise ValueError(f'More than one index {wrid} in frame {i_frame}.')

                mapping_res[wl][i_frame] = wrid_red[res_idx]

            else:
                mapping_res[wl][i_frame] = 0

    return mapping_res


def convert_hb_atom(idx,
                    t,
                    sidechain_ids=None,
                    water_ids=None,
                    wlet_mapping=None,
                    i_frame=None):
    '''
    Convert atom index to hbond string.

    The hbond string indicates the residue of donor and acceptor and wether the
    sidechain or backbone of the residue will be involved.

    Parameters
    ----------
    idx : int
        Atom index of hydrogen bond donor or acceptor.
    t : md.Trajectory
        Trajectory in which the atom index can be found.
    sidechain_ids : np.ndarray or None
        Atom indices of sidechain atoms in trajectory. If None, will be selected
        from t.
    water_ids : np.ndarray or None
        Atom indices of water atoms in trajectory. If None, will be selected
        from t.
    wlet_mapping : dict or None
        Mapping of water residue indices to letter codes.
    i_frame : int or None
        Number of current frame. Needed when wlet mapping is enabled.

    Returns
    -------
    s : str
        Hbond string.
    '''
    # already converted
    if type(idx) == str:
        return idx

    # load water and sidechain atom indices
    if not type(sidechain_ids) == np.ndarray:
        sidechain_ids = t.top.select('is_sidechain')
    if not type(water_ids) == np.ndarray:
        water_ids = t.top.select('is_water')

    a = t.top.atom(idx)
    if idx in water_ids:
        if wlet_mapping:
            s = a.residue.name + str(a.residue.resSeq) + 'w' + f'-{a.element.symbol}'
            for wl in wlet_mapping:
                w_id = wlet_mapping[wl].astype('int')[i_frame]
                if w_id == a.residue.index and w_id != 0:
                    s = wl
        else:
            s = a.residue.name + str(a.residue.resSeq) + 'w' + f'-{a.element.symbol}'
    elif idx in sidechain_ids:
        s = a.residue.name + str(a.residue.resSeq) + 's' + f'-{a.element.symbol}'
    else:
        s = a.residue.name + str(a.residue.resSeq) + 'b' + f'-{a.element.symbol}'
    return s


def hbond_to_string(hbonds,
                    t,
                    wlet_mapping=None):
    '''
    Convert atom indices from mdtraj hbond output to strings indicating residue and sidechain/backbone. Deletes H-Atom.

    Parameters
    ----------
    hbonds : list of np.ndarray
        Output from md.wernet_nilsson().
    t : md.Trajectory
        Trajectory from which the hbonds were computed.

    Returns
    -------
    hbonds_new : list of np.ndarray
        Hbonds with hbond strings instead of atom indices.
    '''
    hbonds_new = []

    # load sidechain and water atom indices
    sidechain_ids = t.top.select('is_sidechain')
    water_ids = t.top.select('is_water')

    for i_frame, frame in enumerate(hbonds):
        if not wlet_mapping:
            donors = np.array([convert_hb_atom(x, t, sidechain_ids, water_ids) for x in frame.T[0]])
            acceptors = np.array([convert_hb_atom(x, t, sidechain_ids, water_ids)
                                  for x in frame.T[2]])
        else:
            donors = np.array([convert_hb_atom(x, t, sidechain_ids, water_ids,
                                               wlet_mapping, i_frame) for x in frame.T[0]])
            acceptors = np.array([convert_hb_atom(x, t, sidechain_ids, water_ids,
                                                  wlet_mapping, i_frame) for x in frame.T[2]])

        frame_new = np.dstack((donors, acceptors))[0]
        hbonds_new.append(frame_new)

    return hbonds_new


def hbond_matrix(hbond_trjs):
    '''
    Extract hbond frequency matrix from list of donor-acceptor arrays for each frame.

    Parameters
    ----------
    hbond_trjs : list
        Contains lists of np.ndarray for each trj for the hydrogen bonds in each
        frame.

    Returns
    -------
    hbond_matrix : np.ndarray
        2D Array of shape (donors,acceptors) with frequency for each hbond.
    donors : list
        Donors cooresponding to indices in H-bond matrix.
    acceptors : list
        Acceptors corresponding to indices in H-bond matrix.

    '''
    # total number of frames
    n_frames_tot = 0

    # total possible donors/acceptors
    donors = []
    acceptors = []

    for hbonds in hbond_trjs:
        # add frames of trjs to total number of frames
        n_frames_tot += len(hbonds)

        # add to list of possible donors and acceptors
        for frame in hbonds:
            don_frame = frame[:, 0]
            acc_frame = frame[:, 1]
            for do in don_frame:
                if do not in donors:
                    donors.append(do)
            for ac in acc_frame:
                if ac not in acceptors:
                    acceptors.append(ac)

    # sort donors/acceptors so mutual atoms are sorted before non mutual donors/acceptors
    donors_sorted = []
    acceptors_sorted = []
    for do in donors:
        if do in acceptors:
            donors_sorted.append(do)
            acceptors_sorted.append(do)

    donors_sorted = sorted(donors_sorted, key=lambda x: _resseq_finder(x))
    acceptors_sorted = sorted(acceptors_sorted, key=lambda x: _resseq_finder(x))

    for do in donors:
        if do not in donors_sorted:
            donors_sorted.append(do)
    for ac in acceptors:
        if ac not in acceptors_sorted:
            acceptors_sorted.append(ac)

    donors = donors_sorted
    acceptors = acceptors_sorted

    # initialize hbond matrix
    hbond_matrix = np.zeros((len(donors), len(acceptors)))

    # set values of hbnod matrix
    for hbonds in hbond_trjs:
        for frame in hbonds:
            for hb in frame:
                i_donor = donors.index(hb[0])
                i_acceptor = acceptors.index(hb[1])

                hbond_matrix[i_donor, i_acceptor] += 1

    # normalize
    hbond_matrix = hbond_matrix / n_frames_tot

    return (hbond_matrix, donors, acceptors)


def _resseq_finder(s):
    '''Get resSeq from donor/acceptor string.'''
    p = re.search(r'[0-9]+', s)
    if p:
        return int(p[0])
    else:
        # hbond string does not include resseq, i.e. letter code
        # return unicode from string + 10000
        return ord(s) + 10000


def hbond_timeline(hbond_trjs, s):
    '''
    Calculate timeline of donors, acceptors to a specified hbond participant.

    Parameters
    ----------
    hbond_trjs : list
        Contains lists of np.ndarray for each trj for the hydrogen bonds in each
        frame.
    s : str
        Hbond string of the H-bond participant to be analyzed.
    '''
    # atoms to which participant donantes to (acc.) and accepts from (don.)
    donates_to = {}
    accepts_from = {}

    # number of frames of individual trajectories and total number of frames
    n_frames_tot = 0
    n_frames = np.zeros(len(hbond_trjs))
    for i_trj, hbonds in enumerate(hbond_trjs):
        n_frames_tot += len(hbonds)
        n_frames[i_trj] = len(hbonds)

    for i_trj, hbonds in enumerate(hbond_trjs):
        for i_frame, frame in enumerate(hbonds):

            # get hbonds in which s donates to other atoms
            mask_don_to = np.zeros(frame.shape, bool) | (frame[:, 0] == s)[:, None]
            don_to_frame = frame[mask_don_to].reshape(-1, 2)

            # extract acceptors
            for ac in don_to_frame[:, 1]:
                if ac not in donates_to:
                    donates_to[ac] = np.zeros(n_frames_tot, dtype=int)
                donates_to[ac][int(n_frames[:i_trj].sum() + i_frame)] += 1

            # get hbonds in which s accepts from other atoms
            mask_acc_from = np.zeros(frame.shape, bool) | (frame[:, 1] == s)[:, None]
            acc_from_frame = frame[mask_acc_from].reshape(-1, 2)

            # extract donors
            for do in acc_from_frame[:, 0]:
                if do not in accepts_from:
                    accepts_from[do] = np.zeros(n_frames_tot, dtype=int)
                accepts_from[do][int(n_frames[:i_trj].sum() + i_frame)] += 1

    return donates_to, accepts_from


def hbond_most_frequent(hbond_trjs, s):
    '''
    Identify most frequent donors and acceptors to specified participant.

    Parameters
    ----------
    hbond_trjs : list
        Contains lists of np.ndarray for each trj for the hydrogen bonds in each
        frame.
    s : str
        Hbond string of the H-bond participant to be analyzed.

    Returns
    -------
    donors_frequency : dict
        Donors, that donate hydrogen bonds to the analyzed participant and their
        frequency how often they donate.
    acceptors_frequency : dict
        Acceptors, that accept hydrogen bonds from analyzed participant and
        their frequency how often they accept.
    '''
    donates_to, accepts_from = hbond_timeline(hbond_trjs, s)

    # total number of frames
    n_frames_tot = len(list(donates_to.values())[0])

    # most common donors and acceptors
    donors_frequency = {}
    acceptors_frequency = {}

    # calculate frequencies
    for do in accepts_from:
        donors_frequency[do] = np.count_nonzero(accepts_from[do]) / n_frames_tot
    for ac in donates_to:
        acceptors_frequency[ac] = np.count_nonzero(donates_to[ac]) / n_frames_tot

    # sort by highest frequency
    donors_frequency = {k: v for k, v in sorted(
        donors_frequency.items(), key=lambda item: item[1], reverse=True)}
    acceptors_frequency = {k: v for k, v in sorted(
        acceptors_frequency.items(), key=lambda item: item[1], reverse=True)}

    return donors_frequency, acceptors_frequency


def plot_frequency(ax, frequency, s, n=6, donors=True):
    '''
    Plot the most frequent donors or acceptors.

    Parameters
    ----------
    ax : plt.Axes
        Matplotlib ax.
    frequency : dict
        Output from hbond_most_frequent.
    s : str
        Name of participant for plot title.
    n : int
        Number of donors/acceptors to plot.
    donors : bool
        Whether to plot donors or acceptors. Color donors blue, acceptors red.
    '''
    x = list(frequency.keys())[:n]
    y = np.array([frequency[x] for x in x]) * 100  # percentage

    if donors:
        ax.bar(range(len(x)), y, color='darkblue')
        ax.set_xticklabels(x, rotation=90)
        ax.set_xlabel('Donors', weight='bold')
    else:
        ax.bar(range(len(x)), y, color='darkred')
        ax.set_xticklabels(x, rotation=90)
        ax.set_xlabel('Acceptors', weight='bold')

    ax.set_xticks(range(n))
    ax.set_ylabel('Frequency [%]')
    ax.set_ylim(0, 100)
    ax.text(0.98,
            0.98,
            s,
            horizontalalignment='right',
            verticalalignment='top',
            transform=ax.transAxes)
